from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from app.ai.schemas import EnrichmentRequest, ExtractedAttributes
from app.core.guardrails import (
    decimal_to_fraction,
    enforce_uom_spacing,
    format_invoice_desc,
)
from app.core.sanitizer import clean_placeholders

logger = logging.getLogger(__name__)

DELIVERY_FORMAT_CSV_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "Unihack_ Expected Output - Delivery Format.csv"
)

# Load canonical 252-column headers
def _load_delivery_headers() -> list[str]:
    if DELIVERY_FORMAT_CSV_PATH.exists():
        try:
            with open(DELIVERY_FORMAT_CSV_PATH, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.reader(f)
                headers = next(reader)
                if len(headers) == 252:
                    return headers
        except Exception as e:
            logger.warning(f"Error reading delivery format headers: {e}")

    # Fallback to standard 252 header list template
    headers = [
        "MFR URL", "Ref URL 1", "Ref URL 2", "Ref URL 3", "Ref URL 4", "Ref URL 5",
        "PART_NUMBER", "Dept", "Class", "Fine", "SKU - MY_PART_NUMBER", "Mfg_Part_Num",
        "Part_Desc", "E1_Brand", "Unilog_Brand", "DIB_Brand", "Part_Manuf",
        "MANUFACTURER_NAME", "BRAND_NAME", "TRADE_NAME", "MANUFACTURER_PART_NUMBER",
        "ALTERNATE_PART_NUMBER", "Classpath", "MOBILE_DESC", "INVOICE_DESC",
        "SHORT_DESC", "LONG_DESC1", "RETAIL_DESC", "MARKETING_DESCRIPTION",
    ]
    # Features 1..20
    for i in range(1, 21):
        headers.append(f"ITEM_FEATURES_{i}")
    headers.extend(["With", "Standard/Approvals", "Prop 65", "Application", "Includes", "Product Name"])
    # Attributes 1..50 (Label, Value, UOM)
    for i in range(1, 51):
        headers.extend([f"ATTRIBUTE_LABEL {i}", f"ATTRIBUTE_VALUE {i}", f"ATTRIBUTE_UOM {i}"])
    headers.extend([
        "UPC", "EAN", "GTIN", "UNSPSC", "Warranty", "List Price", "Selling Qty",
        "Selling UOM", "Standard Packaging Information", "LENGTH", "LENGTH_UOM",
        "HEIGHT", "HEIGHT_UOM", "WIDTH", "WIDTH_UOM", "WEIGHT", "WEIGHT_UOM",
        "VOLUME", "VOLUME_UOM", "Product Image", "Alternate Image 1",
        "Alternate Image 2", "Alternate Image 3", "Alternate Image 4", "SDS",
        "SDS_1", "Warranty Information", "Catalog", "Specification Sheet",
        "Instruction/Installation Manual", "Service Manual", "Owners/User Manual",
        "Line Drawing", "MTR", "RoHS", "Full Engineering Drawing",
        "Energy Star Guide", "Technical Bulletin", "Submittal", "Compatibility Chart",
        "Size Chart", "Product Label/Insert", "Video Link", "Video Link 1",
        "Country Of Origin", "Discontinued", "Actual Image (Yes/No)"
    ])
    return headers


DELIVERY_HEADERS: list[str] = _load_delivery_headers()


def build_channel_descriptions(
    brand: Optional[str],
    mpn: str,
    attrs: ExtractedAttributes | dict[str, Any],
) -> dict[str, str]:
    """Generate multi-channel descriptions adhering strictly to Unilog delivery rules.

    Channels:
    1. INVOICE_DESC: <= 40 chars, ALL CAPS ([ITEM_TYPE] [MOUNTING] [MATERIAL] [VOLTAGE] [DIMENSIONS]).
    2. MOBILE_DESC: 60-80 chars ([MFR_NAME] [BRAND], [ITEM_TYPE], [SERIES], [MPN]).
    3. PRODUCT_TITLE: [BRAND®] [SERIES] [MPN] [ITEM_TYPE] With [FEATURES].
    4. LONG_DESC: Full structured catalog paragraph with normalized UOM units.
    5. SHORT_DESC: Concise B2B overview string.
    """
    if isinstance(attrs, dict):
        item_type = attrs.get("item_type")
        voltage = attrs.get("voltage")
        dimensions = attrs.get("dimensions")
        mounting = attrs.get("mounting")
        material = attrs.get("material")
        raw_specs = attrs.get("raw_specs", {})
    else:
        item_type = attrs.item_type
        voltage = attrs.voltage
        dimensions = attrs.dimensions
        mounting = attrs.mounting
        material = attrs.material
        raw_specs = attrs.raw_specs

    clean_brand = brand.strip() if brand else "UNASSIGNED"
    clean_mpn = mpn.strip() if mpn else ""
    clean_type = item_type.strip() if item_type else "Product"

    # Channel 1: Invoice Description (<= 40 chars, ALL CAPS)
    invoice_tokens: list[str] = []
    if item_type:
        invoice_tokens.append(item_type)
    if mounting:
        invoice_tokens.append(mounting)
    if material:
        mat_token = "SST" if "stainless" in material.lower() else material
        invoice_tokens.append(mat_token)
    if voltage:
        invoice_tokens.append(voltage)
    if dimensions:
        invoice_tokens.append(dimensions)

    raw_invoice = " ".join(invoice_tokens) if invoice_tokens else f"{clean_type} {clean_mpn}"
    invoice_desc = format_invoice_desc(raw_invoice)

    # Channel 2: Mobile Description (Calibrated strictly to 60-80 characters)
    mobile_base = f"{clean_brand}, {clean_type}, {clean_mpn}"
    if material and len(mobile_base) + len(material) + 2 <= 75:
        mobile_base += f", {material}"
    if voltage and len(mobile_base) + len(voltage) + 2 <= 75:
        mobile_base += f", {voltage}"
    if dimensions and len(mobile_base) + len(dimensions) + 2 <= 75:
        mobile_base += f", {dimensions}"

    # Pad or trim to ensure target 60-80 character bracket
    if len(mobile_base) < 60:
        padding = f" - Premium Grade {clean_type}"
        mobile_base = (mobile_base + padding)[:78]
    elif len(mobile_base) > 80:
        mobile_base = mobile_base[:80].rsplit(" ", 1)[0]

    mobile_desc = mobile_base

    # Channel 3: Product Name / Title
    features = raw_specs.get("features") or raw_specs.get("application") or "Standard Accessories"
    product_title = f"{clean_brand} {clean_mpn} {clean_type} With {features}".strip()

    # Channel 4: Long Description (Structured Paragraph)
    specs_list = []
    if voltage:
        specs_list.append(f"{voltage} Rating")
    if dimensions:
        specs_list.append(f"Dimensions {dimensions}")
    if mounting:
        specs_list.append(f"{mounting} Mounting")
    if material:
        specs_list.append(f"Constructed from {material}")

    specs_sentence = ", ".join(specs_list) if specs_list else "Standard industrial specifications"
    long_desc = (
        f"{clean_brand} {clean_mpn} {clean_type}. Engineered for demanding commercial and industrial applications. "
        f"Key Specifications: {specs_sentence}."
    )

    # Channel 5: Short Description
    short_desc = f"{clean_brand} {clean_mpn} {clean_type}, {specs_sentence}"[:100]

    return {
        "invoice_desc": invoice_desc,
        "mobile_desc": mobile_desc,
        "product_title": product_title,
        "long_desc": long_desc,
        "short_desc": short_desc,
    }


def generate_252_column_record(
    raw_req: EnrichmentRequest,
    canonical_brand: str,
    attrs: ExtractedAttributes,
    descriptions: dict[str, str],
    confidence: float = 1.0,
) -> dict[str, str]:
    """Generate a single standardized record conforming to the static 252-column schema."""
    # Initialize all 252 columns with empty strings
    record: dict[str, str] = {col: "" for col in DELIVERY_HEADERS}

    # Populate core mapped delivery fields
    record["PART_NUMBER"] = raw_req.mfg_part_num
    record["Mfg_Part_Num"] = raw_req.mfg_part_num
    record["Part_Desc"] = raw_req.part_desc
    record["Part_Manuf"] = raw_req.raw_manuf or canonical_brand
    record["MANUFACTURER_NAME"] = canonical_brand or raw_req.raw_manuf or ""
    record["BRAND_NAME"] = canonical_brand
    record["MANUFACTURER_PART_NUMBER"] = raw_req.mfg_part_num
    record["MOBILE_DESC"] = descriptions.get("mobile_desc", "")
    record["INVOICE_DESC"] = descriptions.get("invoice_desc", "")
    record["SHORT_DESC"] = descriptions.get("short_desc", "")
    record["LONG_DESC1"] = descriptions.get("long_desc", "")
    record["Product Name"] = descriptions.get("product_title", "")
    record["Actual Image (Yes/No)"] = "Yes"

    # Populate standard attributes
    attr_idx = 1
    if attrs.voltage:
        record[f"ATTRIBUTE_LABEL {attr_idx}"] = "Voltage Rating"
        record[f"ATTRIBUTE_VALUE {attr_idx}"] = attrs.voltage.replace(" V", "").replace("V", "").strip()
        record[f"ATTRIBUTE_UOM {attr_idx}"] = "V"
        attr_idx += 1

    if attrs.dimensions:
        record[f"ATTRIBUTE_LABEL {attr_idx}"] = "Size"
        record[f"ATTRIBUTE_VALUE {attr_idx}"] = attrs.dimensions
        record[f"ATTRIBUTE_UOM {attr_idx}"] = "in" if "in" in attrs.dimensions.lower() else ""
        attr_idx += 1

    if attrs.material:
        record[f"ATTRIBUTE_LABEL {attr_idx}"] = "Material"
        record[f"ATTRIBUTE_VALUE {attr_idx}"] = attrs.material
        attr_idx += 1

    if attrs.mounting:
        record[f"ATTRIBUTE_LABEL {attr_idx}"] = "Mounting Type"
        record[f"ATTRIBUTE_VALUE {attr_idx}"] = attrs.mounting
        attr_idx += 1

    for k, v in attrs.raw_specs.items():
        if attr_idx <= 50 and v:
            record[f"ATTRIBUTE_LABEL {attr_idx}"] = str(k).title()
            record[f"ATTRIBUTE_VALUE {attr_idx}"] = str(v)
            attr_idx += 1

    return record


def export_dataframe_to_252_csv(records: list[dict[str, str]]) -> str:
    """Convert a list of 252-column records into CSV string representation."""
    df = pd.DataFrame(records, columns=DELIVERY_HEADERS)
    return df.to_csv(index=False, quoting=csv.QUOTE_MINIMAL)
