from __future__ import annotations

import csv
import io
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


class ExpectedSchema:
    """Canonical 252-Column Unilog Schema Definition and Metadata."""

    @staticmethod
    def load_columns() -> list[str]:
        if DELIVERY_FORMAT_CSV_PATH.exists():
            try:
                with open(DELIVERY_FORMAT_CSV_PATH, "r", encoding="utf-8", errors="ignore") as f:
                    reader = csv.reader(f)
                    headers = next(reader)
                    if len(headers) == 252:
                        return headers
            except Exception as e:
                logger.warning(f"Error reading delivery format headers: {e}")

        # Fallback canonical 252 header list
        headers = [
            "MFR URL", "Ref URL 1", "Ref URL 2", "Ref URL 3", "Ref URL 4", "Ref URL 5",
            "PART_NUMBER", "Dept", "Class", "Fine", "SKU - MY_PART_NUMBER", "Mfg_Part_Num",
            "Part_Desc", "E1_Brand", "Unilog_Brand", "DIB_Brand", "Part_Manuf",
            "MANUFACTURER_NAME", "BRAND_NAME", "TRADE_NAME", "MANUFACTURER_PART_NUMBER",
            "ALTERNATE_PART_NUMBER", "Classpath", "MOBILE_DESC", "INVOICE_DESC",
            "SHORT_DESC", "LONG_DESC1", "RETAIL_DESC", "MARKETING_DESCRIPTION",
        ]
        for i in range(1, 21):
            headers.append(f"ITEM_FEATURES_{i}")
        headers.extend(["With", "Standard/Approvals", "Prop 65", "Application", "Includes", "Product Name"])
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
            "Country Of Origin", "Discontinued", "Actual Image (Yes/No)",
        ])
        return headers

    REQUIRED_COLUMNS: list[str] = [
        "PART_NUMBER",
        "Mfg_Part_Num",
        "Part_Desc",
        "MANUFACTURER_NAME",
        "BRAND_NAME",
        "MANUFACTURER_PART_NUMBER",
        "INVOICE_DESC",
        "MOBILE_DESC",
        "Product Name",
        "Actual Image (Yes/No)",
    ]


DELIVERY_HEADERS: list[str] = ExpectedSchema.load_columns()


def build_channel_descriptions(
    brand: Optional[str],
    mpn: str,
    attrs: ExtractedAttributes | dict[str, Any],
) -> dict[str, str]:
    """Generate multi-channel descriptions adhering strictly to Unilog delivery rules."""
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
    clean_type = item_type.strip() if item_type else "Commercial Product"
    clean_mpn = mpn.strip()

    # 1. INVOICE_DESC: <= 40 chars, ALL CAPS
    inv_components = [clean_type]
    if mounting:
        inv_components.append(mounting)
    if material:
        inv_components.append(material)
    if voltage:
        inv_components.append(voltage)
    if dimensions:
        inv_components.append(dimensions)

    raw_invoice = " ".join(inv_components)
    invoice_desc = format_invoice_desc(raw_invoice)

    # 2. MOBILE_DESC: 60-80 chars
    mobile_parts = [clean_brand, clean_type, clean_mpn]
    if voltage and len(", ".join(mobile_parts)) + len(voltage) + 2 <= 78:
        mobile_parts.append(voltage)
    if dimensions and len(", ".join(mobile_parts)) + len(dimensions) + 2 <= 78:
        mobile_parts.append(dimensions)

    base_mobile = ", ".join(mobile_parts)
    if len(base_mobile) < 60:
        base_mobile = f"{base_mobile} - Commercial Grade {clean_type}"
    mobile_desc = base_mobile[:80].strip()

    # 3. PRODUCT_TITLE: [BRAND] [MPN] [ITEM_TYPE]
    title_parts = [clean_brand, clean_mpn, clean_type]
    if material:
        title_parts.append(f"in {material}")
    if dimensions:
        title_parts.append(f"({dimensions})")
    product_title = " ".join(title_parts)

    # 4. LONG_DESC: Full structured paragraph
    long_desc_lines = [
        f"The {clean_brand} {clean_mpn} is a commercial-grade {clean_type.lower()} designed for professional and industrial applications.",
    ]
    if voltage or dimensions or material:
        specs_summary = []
        if material:
            specs_summary.append(f"durable {material.lower()} construction")
        if voltage:
            specs_summary.append(f"rated for {voltage}")
        if dimensions:
            specs_summary.append(f"measuring {dimensions}")
        long_desc_lines.append(f"Engineered with {', '.join(specs_summary)}.")

    if raw_specs:
        spec_items = [f"{k}: {v}" for k, v in raw_specs.items()]
        long_desc_lines.append(f"Key Specifications include {'; '.join(spec_items)}.")

    long_desc = " ".join(long_desc_lines)

    # 5. SHORT_DESC: Concise summary
    short_desc = f"{clean_brand} {clean_mpn} {clean_type}"
    if voltage:
        short_desc += f", {voltage}"
    if dimensions:
        short_desc += f", {dimensions}"

    return {
        "invoice_desc": invoice_desc,
        "mobile_desc": mobile_desc,
        "product_title": product_title,
        "long_desc": long_desc,
        "short_desc": short_desc,
    }


class SchemaMapper:
    """Maps enriched product specifications into the exact 252-column Unilog delivery dictionary."""

    @staticmethod
    def map_to_252_column_record(
        raw_req: EnrichmentRequest,
        canonical_brand: str,
        attrs: ExtractedAttributes,
        descriptions: dict[str, str],
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        record: dict[str, Any] = {col: "" for col in DELIVERY_HEADERS}

        clean_mpn = raw_req.mfg_part_num.strip()
        brand_final = canonical_brand or attrs.brand or ""
        manuf_final = brand_final.replace("®", "").replace("™", "").strip()

        # Core Identification
        record["PART_NUMBER"] = clean_mpn
        record["Mfg_Part_Num"] = clean_mpn
        record["Part_Desc"] = clean_placeholders(raw_req.part_desc) or raw_req.part_desc
        record["SKU - MY_PART_NUMBER"] = clean_mpn
        record["MANUFACTURER_PART_NUMBER"] = clean_mpn

        # Brand / Manufacturer Fields
        record["E1_Brand"] = brand_final
        record["Unilog_Brand"] = brand_final
        record["DIB_Brand"] = brand_final
        record["Part_Manuf"] = manuf_final
        record["MANUFACTURER_NAME"] = manuf_final
        record["BRAND_NAME"] = brand_final
        record["TRADE_NAME"] = brand_final

        # Multi-Channel Descriptions
        record["INVOICE_DESC"] = descriptions.get("invoice_desc", "")
        record["MOBILE_DESC"] = descriptions.get("mobile_desc", "")
        record["SHORT_DESC"] = descriptions.get("short_desc", "")
        record["LONG_DESC1"] = descriptions.get("long_desc", "")
        record["RETAIL_DESC"] = descriptions.get("product_title", "")
        record["MARKETING_DESCRIPTION"] = descriptions.get("long_desc", "")
        record["Product Name"] = descriptions.get("product_title", "")

        # Default Metadata
        record["Actual Image (Yes/No)"] = "Yes"
        record["Selling Qty"] = "1"
        record["Selling UOM"] = "EA"
        record["Country Of Origin"] = "US"
        record["Discontinued"] = "No"

        # Map Extracted Specs to Attributes 1..50 (starting with Voltage, Dimensions, Material, Mounting, Item Type)
        slot = 1
        spec_mappings = [
            ("Voltage", attrs.voltage, "V" if attrs.voltage else None),
            ("Dimensions", attrs.dimensions, "in" if attrs.dimensions else None),
            ("Mounting", attrs.mounting, None),
            ("Material", attrs.material, None),
            ("Item Type", attrs.item_type, None),
        ]

        for label, val, default_uom in spec_mappings:
            if val and slot <= 50:
                val_str = str(val)
                # If UOM is embedded in value (e.g. "120 V"), extract clean value and UOM
                if default_uom and val_str.endswith(f" {default_uom}"):
                    val_clean = val_str[:-len(f" {default_uom}")].strip()
                    uom_clean = default_uom
                else:
                    val_clean = val_str
                    uom_clean = default_uom or ""

                record[f"ATTRIBUTE_LABEL {slot}"] = label
                record[f"ATTRIBUTE_VALUE {slot}"] = val_clean
                record[f"ATTRIBUTE_UOM {slot}"] = uom_clean
                slot += 1

        # Additional raw_specs
        for k, v in attrs.raw_specs.items():
            if slot <= 50:
                record[f"ATTRIBUTE_LABEL {slot}"] = k
                record[f"ATTRIBUTE_VALUE {slot}"] = str(v)
                record[f"ATTRIBUTE_UOM {slot}"] = ""
                slot += 1

        # Features 1..20
        feat_idx = 1
        if attrs.material and feat_idx <= 20:
            record[f"ITEM_FEATURES_{feat_idx}"] = f"Constructed with high-grade {attrs.material}"
            feat_idx += 1
        if attrs.voltage and feat_idx <= 20:
            record[f"ITEM_FEATURES_{feat_idx}"] = f"Operates at standard {attrs.voltage}"
            feat_idx += 1
        if attrs.dimensions and feat_idx <= 20:
            record[f"ITEM_FEATURES_{feat_idx}"] = f"Precision dimensions: {attrs.dimensions}"
            feat_idx += 1

        return record


def generate_252_column_record(
    raw_req: EnrichmentRequest,
    canonical_brand: str,
    attrs: ExtractedAttributes,
    descriptions: dict[str, str],
    confidence: float = 1.0,
) -> dict[str, Any]:
    return SchemaMapper.map_to_252_column_record(
        raw_req=raw_req,
        canonical_brand=canonical_brand,
        attrs=attrs,
        descriptions=descriptions,
        confidence=confidence,
    )


def export_dataframe_to_252_csv(df: pd.DataFrame | list[dict[str, Any]]) -> str:
    """Export DataFrame or list of dictionary records as a strictly formatted, CSV-safe 252-column text payload."""
    if isinstance(df, list):
        df = pd.DataFrame(df)
    output = io.StringIO()
    aligned_df = df.reindex(columns=DELIVERY_HEADERS, fill_value="")
    aligned_df.to_csv(output, index=False, quoting=csv.QUOTE_MINIMAL)
    return output.getvalue()
