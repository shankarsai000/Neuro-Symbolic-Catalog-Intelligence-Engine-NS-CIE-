from __future__ import annotations

import csv
import io
import logging
import re
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
from app.data.master_repository import master_data_repository

logger = logging.getLogger(__name__)

DELIVERY_FORMAT_CSV_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "Unihack_ Expected Output - Delivery Format.csv"
)


TAXONOMY_MAP = {
    "dishwasher": {
        "Dept": "Appliances",
        "Class": "Large Appliances",
        "Fine": "Dishwashers",
        "Classpath": "Appliances & Consumer Electronics>Kitchen Appliances>Built-In Dishwashers",
    },
    "faucet": {
        "Dept": "Plumbing",
        "Class": "Faucets & Stems",
        "Fine": "Kitchen Faucets",
        "Classpath": "Plumbing>Faucets>Kitchen Faucets",
    },
    "saw": {
        "Dept": "Tools & Hardware",
        "Class": "Power Tool Accessories",
        "Fine": "Saw Blades",
        "Classpath": "Tools & Hardware>Power Tool Accessories>Saw Blades",
    },
    "disc": {
        "Dept": "Tools & Hardware",
        "Class": "Abrasives",
        "Fine": "Cutting Discs",
        "Classpath": "Tools & Hardware>Abrasives>Cutting & Grinding Discs",
    },
    "elbow": {
        "Dept": "Plumbing",
        "Class": "Pipe Fittings",
        "Fine": "Elbows",
        "Classpath": "Plumbing>Pipe & Fittings>Elbows",
    },
}


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
    manufacturer: Optional[str] = None,
) -> dict[str, str]:
    """Generate multi-channel descriptions adhering strictly to Unilog category-specialized rules."""
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
        raw_specs = attrs.raw_specs or {}

    clean_brand = brand.strip() if brand else "UNASSIGNED"
    clean_type = item_type.strip() if item_type else "Commercial Product"
    clean_mpn = mpn.strip()

    # Extract specialized specs
    flow_rate = raw_specs.get("FlowRate")
    conn_type = raw_specs.get("ConnectionType")
    press_rating = raw_specs.get("PressureRating")
    finish = raw_specs.get("Finish")
    grit = raw_specs.get("Grit")
    arbor = raw_specs.get("ArborSize")
    pack_qty = raw_specs.get("PackQuantity")
    amperage = raw_specs.get("Amperage")
    sound_level = raw_specs.get("SoundLevel")
    series = raw_specs.get("Series")
    cycles = raw_specs.get("Number of Wash Cycles")
    depth_open = raw_specs.get("DepthWithDoorOpen")
    min_height = raw_specs.get("Minimum Height")
    max_height = raw_specs.get("Maximum Height")
    color = raw_specs.get("Color")
    with_feat = raw_specs.get("With")
    add_info = raw_specs.get("Additional Information")

    # Determine Category Strategy
    type_lower = clean_type.lower()
    is_faucet = "faucet" in type_lower
    is_fitting = any(f in type_lower for f in ["fitting", "elbow", "tee", "coupling", "adapter", "union", "nipple", "flange"])
    is_abrasive = any(a in type_lower for a in ["disc", "belt", "wheel", "blade", "cut-off", "cutoff", "abrasive", "grinding"])
    is_appliance = any(ap in type_lower for ap in ["dishwasher", "washer", "dryer", "refrigerator", "range", "oven"])

    # 1. INVOICE_DESC Generation (<= 40 chars, ALL CAPS, semantically dense)
    inv_components = [clean_type.upper()]
    if is_faucet:
        if mounting:
            inv_components.append(mounting)
        if flow_rate:
            inv_components.append(flow_rate)
        if finish:
            inv_components.append(finish)
        elif material:
            inv_components.append(material)
    elif is_fitting:
        if dimensions:
            inv_components.append(dimensions)
        if conn_type:
            inv_components.append(conn_type)
        if material:
            inv_components.append(material)
        if press_rating:
            inv_components.append(press_rating)
    elif is_abrasive:
        if dimensions:
            inv_components.append(dimensions)
        if arbor:
            inv_components.append(arbor)
        if grit:
            inv_components.append(grit)
        elif material:
            inv_components.append(material)
        if pack_qty:
            inv_components.append(pack_qty)
    elif is_appliance:
        inv_components = ["DISHWASHER" if "dishwasher" in type_lower else clean_type.upper()]
        if mounting:
            inv_components.append("BLTLN" if "built" in mounting.lower() else mounting.upper())
        if cycles:
            try:
                c_int = str(int(float(cycles)))
                inv_components.append(c_int)
            except (ValueError, TypeError):
                inv_components.append(str(cycles).upper())
        if material:
            inv_components.append("SST" if "stainless" in material.lower() else material.upper())
        if color:
            inv_components.append("SST" if "stainless" in color.lower() else color.upper())
        if voltage:
            inv_components.append(voltage.replace(" ", "").upper())
        if amperage:
            inv_components.append(amperage.replace(" ", "").upper())
        if depth_open:
            d_val = depth_open.replace(" ", "").upper()
            if not d_val.endswith("IN"):
                d_val += "IN"
            candidate = " ".join(inv_components + [d_val])
            if len(candidate) <= 40:
                inv_components.append(d_val)
            elif sound_level:
                inv_components.append(sound_level.replace(" ", "").upper())
        elif sound_level:
            inv_components.append(sound_level.replace(" ", "").upper())
    else:
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
    if len(invoice_desc) > 40:
        invoice_desc = invoice_desc[:40].rstrip()

    # 2. MOBILE_DESC Generation (60-80 chars)
    mobile_parts = []
    if manufacturer and manufacturer.strip() and manufacturer.strip().upper() != clean_brand.upper():
        mobile_parts.append(manufacturer.strip())
    mobile_parts.extend([clean_brand, clean_type])
    if series:
        mobile_parts.append(series)
    mobile_parts.append(clean_mpn)
    if mounting:
        mobile_parts.append(f"{mounting} Mounting" if not mounting.lower().endswith("mounting") else mounting)
    if material:
        mobile_parts.append(material)

    mobile_desc = ", ".join(mobile_parts)
    if len(mobile_desc) > 80:
        mobile_desc = mobile_desc[:80].rstrip()

    # 3. SHORT_DESC Generation
    short_parts = [clean_brand]
    if series:
        short_parts.append(series)
    short_parts.extend([clean_mpn, clean_type])
    if with_feat:
        short_parts.append(with_feat)
    if mounting:
        short_parts.append(f"{mounting} Mounting")
    if cycles:
        try:
            c_int = str(int(float(cycles)))
            short_parts.append(f"{c_int}-Wash Cycle")
        except (ValueError, TypeError):
            short_parts.append(f"{cycles}-Wash Cycle")
    if material:
        short_parts.append(material)
    if color and material and color.upper() != material.upper():
        short_parts.append(color)

    short_desc = ", ".join(short_parts)

    # 4. PRODUCT_TITLE Generation (RETAIL_DESC)
    title_parts = [clean_brand]
    if series and series.lower() != clean_brand.lower():
        title_parts.append(series)
    title_parts.append(clean_type)
    if mounting:
        title_parts.append(f"{mounting} Mounting")
    if cycles:
        try:
            c_int = str(int(float(cycles)))
            title_parts.append(f"{c_int}-Wash Cycle")
        except (ValueError, TypeError):
            title_parts.append(f"{cycles}-Wash Cycle")
    if material:
        title_parts.append(material)
    if color and material and color.upper() != material.upper():
        title_parts.append(color)

    product_title = ", ".join(title_parts)

    # 5. LONG_DESC Generation (Deterministic facts assembly)
    long_parts = []
    header_str = f"{clean_brand} {clean_type}".strip()
    if with_feat:
        header_str += f" {with_feat}"
    long_parts.append(header_str)
    if series:
        long_parts.append(series)
    if cycles:
        try:
            c_int = str(int(float(cycles)))
            long_parts.append(f"{c_int} Wash Cycles")
        except (ValueError, TypeError):
            long_parts.append(f"{cycles} Wash Cycles")
    if voltage:
        long_parts.append(voltage if voltage.endswith("V") else f"{voltage} V")
    if amperage:
        long_parts.append(amperage if amperage.endswith("A") else f"{amperage} A")
    if mounting:
        long_parts.append(f"{mounting} Mounting" if not mounting.lower().endswith("mounting") else mounting)
    if dimensions:
        long_parts.append(dimensions)
    if depth_open:
        long_parts.append(f"{depth_open} Depth With Door Open" if "depth" not in depth_open.lower() else depth_open)
    if min_height:
        long_parts.append(f"{min_height} Minimum Height" if "minimum height" not in min_height.lower() else min_height)
    if max_height:
        long_parts.append(f"{max_height} Maximum Height" if "maximum height" not in max_height.lower() else max_height)
    if sound_level:
        long_parts.append(sound_level if sound_level.endswith("dBA") else f"{sound_level} dBA Sound Level")
    if material:
        long_parts.append(material)
    if color:
        long_parts.append(color)

    long_desc = ", ".join(long_parts)
    if add_info:
        long_desc += f", Additional Information: {add_info}"

    return {
        "invoice_desc": invoice_desc,
        "mobile_desc": mobile_desc,
        "short_desc": short_desc,
        "long_desc": long_desc,
        "product_title": product_title,
    }


class AttributeSlotRegistry:
    """Category-aware canonical fixed attribute slot registry preventing positional slot shifting."""

    DISHWASHER_SLOTS = [
        ("Series", ["series"]),
        ("Model", ["model", "model_number"]),
        ("Number of Wash Cycles", ["number of wash cycles", "wash cycles", "cycles", "number of cycles"]),
        ("Voltage Rating", ["voltage rating", "voltage", "volts"]),
        ("Amperage Rating", ["amperage rating", "amperage", "amps"]),
        ("Mounting Type", ["mounting type", "mounting"]),
        ("Plug Type", ["plug type"]),
        ("Size", ["size", "overall dimensions", "dimensions"]),
        ("Depth With Door Open", ["depth with door open", "depth open"]),
        ("Minimum Height", ["minimum height", "min height"]),
        ("Maximum Height", ["maximum height", "max height"]),
        ("Sound Level", ["sound level", "sound", "dba"]),
        ("Material", ["material", "tub material"]),
        ("Color", ["color", "finish"]),
        ("Additional Information", ["additional information", "features", "notes"]),
    ]

    FAUCET_SLOTS = [
        ("Series", ["series"]),
        ("Model", ["model", "model_number"]),
        ("Flow Rate", ["flow rate", "flowrate", "gpm"]),
        ("Mounting Type", ["mounting type", "mounting"]),
        ("Connection Type", ["connection type", "connection"]),
        ("Connection Size", ["connection size"]),
        ("Spout Reach", ["spout reach"]),
        ("Finish", ["finish", "color"]),
        ("Material", ["material"]),
        ("Additional Information", ["additional information", "notes"]),
    ]

    FITTING_SLOTS = [
        ("Series", ["series"]),
        ("Model", ["model", "model_number"]),
        ("Connection Type", ["connection type", "connection"]),
        ("Connection Size", ["connection size", "size"]),
        ("Pressure Rating", ["pressure rating", "pressure"]),
        ("Material", ["material"]),
        ("Additional Information", ["additional information", "notes"]),
    ]

    ABRASIVE_SLOTS = [
        ("Item Type", ["item type", "type"]),
        ("Dimensions", ["dimensions", "size"]),
        ("Grit", ["grit", "grit rating"]),
        ("Arbor Size", ["arbor size", "arbor"]),
        ("Abrasive Material", ["abrasive material", "material"]),
        ("Pack Quantity", ["pack quantity", "pack qty", "quantity"]),
        ("Additional Information", ["additional information", "notes"]),
    ]

    DEFAULT_SLOTS = [
        ("Series", ["series"]),
        ("Model", ["model", "model_number"]),
        ("Item Type", ["item type", "type"]),
        ("Voltage Rating", ["voltage rating", "voltage"]),
        ("Amperage Rating", ["amperage rating", "amperage"]),
        ("Dimensions", ["dimensions", "size"]),
        ("Mounting Type", ["mounting type", "mounting"]),
        ("Material", ["material"]),
        ("Color", ["color", "finish"]),
        ("Sound Level", ["sound level"]),
        ("Additional Information", ["additional information", "notes"]),
    ]

    @classmethod
    def get_category_schema(cls, item_type: str) -> list[tuple[str, list[str]]]:
        t = (item_type or "").lower()
        if "dishwasher" in t or "appliance" in t:
            return cls.DISHWASHER_SLOTS
        elif "faucet" in t:
            return cls.FAUCET_SLOTS
        elif any(k in t for k in ["fitting", "elbow", "tee", "coupling", "adapter", "union", "flange"]):
            return cls.FITTING_SLOTS
        elif any(k in t for k in ["disc", "belt", "wheel", "blade", "cut-off", "abrasive", "grinding"]):
            return cls.ABRASIVE_SLOTS
        return cls.DEFAULT_SLOTS

    @classmethod
    def map_specs_to_fixed_slots(
        cls,
        spec_dict: dict[str, Any],
        item_type: str,
        record: dict[str, Any],
    ) -> None:
        schema_slots = cls.get_category_schema(item_type)

        # Normalize keys in input spec_dict
        norm_spec_dict = {}
        for k, v in spec_dict.items():
            norm_key = re.sub(r"[\_\-\s]+", " ", str(k)).strip().lower()
            norm_spec_dict[norm_key] = (k, v)

        used_spec_keys = set()

        for slot_idx, (canonical_label, aliases) in enumerate(schema_slots, start=1):
            if slot_idx > 15:
                break

            matched_val = None
            matched_key = None

            for alias in aliases:
                norm_alias = re.sub(r"[\_\-\s]+", " ", alias).strip().lower()
                if norm_alias in norm_spec_dict:
                    matched_key, matched_val = norm_spec_dict[norm_alias]
                    used_spec_keys.add(matched_key)
                    break

            if matched_val is not None and str(matched_val).strip() != "":
                val_str = str(matched_val).strip()
                uom = ""

                # Extract UOM if present in value string
                m = re.match(r"^([\d\-\/\.\s]+)\s*([A-Za-z]+)$", val_str)
                if m and m.group(2) in ("V", "A", "dBA", "in", "GPM", "PSI", "kW-hr"):
                    val_str = m.group(1).strip()
                    uom = m.group(2).strip()

                record[f"ATTRIBUTE_LABEL {slot_idx}"] = canonical_label
                record[f"ATTRIBUTE_VALUE {slot_idx}"] = val_str
                record[f"ATTRIBUTE_UOM {slot_idx}"] = uom
            else:
                # Keep slot empty! NO SHIFTING!
                record[f"ATTRIBUTE_LABEL {slot_idx}"] = canonical_label
                record[f"ATTRIBUTE_VALUE {slot_idx}"] = ""
                record[f"ATTRIBUTE_UOM {slot_idx}"] = ""

        # Place any remaining unmapped extra attributes into slots 16..50
        extra_slot = 16
        excluded_keys = {
            "classpath", "dept", "class", "fine", "product image", "alternate image 1",
            "alternate image 2", "alternate image 3", "alternate image 4",
            "specification sheet", "with", "standard/approvals", "warranty",
            "marketing_description", "marketing description", "product name",
            "item type", "item_type", "spec_sections", "spec sections",
            "ref url 1", "ref url 2", "ref url 3", "ref url 4", "ref url 5",
        }
        for k, v in spec_dict.items():
            if k in used_spec_keys:
                continue
            if str(k).lower() in excluded_keys or str(k).lower().startswith("item_features"):
                continue
            if extra_slot > 50:
                break
            val_str = str(v).strip()
            if not val_str:
                continue
            uom = ""
            m = re.match(r"^([\d\-\/\.\s]+)\s*([A-Za-z]+)$", val_str)
            if m and m.group(2) in ("V", "A", "dBA", "in", "GPM", "PSI", "kW-hr"):
                val_str = m.group(1).strip()
                uom = m.group(2).strip()

            record[f"ATTRIBUTE_LABEL {extra_slot}"] = str(k)
            record[f"ATTRIBUTE_VALUE {extra_slot}"] = val_str
            record[f"ATTRIBUTE_UOM {extra_slot}"] = uom
            extra_slot += 1


class SchemaMapper:
    """Generic, evidence-driven mapper transforming enriched attributes into official 252-column delivery format."""

    @staticmethod
    def map_to_252_column_record(
        raw_req: EnrichmentRequest,
        canonical_brand: str,
        attrs: ExtractedAttributes,
        descriptions: dict[str, str],
        confidence: float = 1.0,
        canonical_manufacturer: Optional[str] = None,
    ) -> dict[str, Any]:
        record = {hdr: "" for hdr in DELIVERY_HEADERS}
        clean_mpn = (raw_req.mfg_part_num or attrs.mpn or "").strip().upper()
        raw_specs = attrs.raw_specs or {}
        brand_final = canonical_brand or attrs.brand or ""
        manuf_final = canonical_manufacturer or master_data_repository.manufacturers.get_manufacturer_for_brand(brand_final) or brand_final

        # Core Identification
        record["PART_NUMBER"] = clean_mpn
        record["Mfg_Part_Num"] = clean_mpn
        record["Part_Desc"] = clean_placeholders(raw_req.part_desc) or raw_req.part_desc
        record["SKU - MY_PART_NUMBER"] = raw_specs.get("SKU") or getattr(attrs, "sku", None) or clean_mpn
        record["MANUFACTURER_PART_NUMBER"] = clean_mpn

        # Brand / Manufacturer Fields
        record["E1_Brand"] = raw_req.e1_brand if raw_req.e1_brand else "-- Unbranded --"
        record["Unilog_Brand"] = raw_req.unilog_brand if raw_req.unilog_brand else "-- No Unilog Brand --"
        record["DIB_Brand"] = raw_req.dib_brand if raw_req.dib_brand else "-- No DIB Brand --"
        record["Part_Manuf"] = raw_req.raw_manuf if raw_req.raw_manuf else manuf_final
        record["MANUFACTURER_NAME"] = manuf_final
        record["BRAND_NAME"] = brand_final
        record["TRADE_NAME"] = ""

        # Taxonomy Fields
        item_lower = (attrs.item_type or "").lower()
        for key, tax in TAXONOMY_MAP.items():
            if key in item_lower:
                record["Dept"] = tax["Dept"]
                record["Class"] = tax["Class"]
                record["Fine"] = tax["Fine"]
                record["Classpath"] = tax["Classpath"]
                break

        # MFR URL & Metadata
        mfr_url_val = raw_specs.get("MFR URL") or attrs.mfr_url
        if mfr_url_val:
            record["MFR URL"] = mfr_url_val
        elif brand_final:
            canonical_b, _ = master_data_repository.brands.resolve_canonical_brand(brand_final)
            clean_b = (canonical_b or brand_final).strip().replace("®", "").replace("™", "").lower()
            domain = None
            for k, d in master_data_repository.brands.brand_domains.items():
                if k.strip().replace("®", "").replace("™", "").lower() == clean_b:
                    domain = d
                    break
            if domain:
                record["MFR URL"] = f"https://{domain}/product/{clean_mpn}"

        record["Ref URL 1"] = raw_specs.get("Ref URL 1", "")
        record["Ref URL 2"] = raw_specs.get("Ref URL 2", "")
        record["With"] = raw_specs.get("With", "")
        record["Standard/Approvals"] = raw_specs.get("Standard/Approvals", "")
        record["Warranty"] = raw_specs.get("Warranty", "")
        record["Product Image"] = raw_specs.get("Product Image", "")
        record["Alternate Image 1"] = raw_specs.get("Alternate Image 1", "")
        record["Alternate Image 2"] = raw_specs.get("Alternate Image 2", "")
        record["Alternate Image 3"] = raw_specs.get("Alternate Image 3", "")
        record["Alternate Image 4"] = raw_specs.get("Alternate Image 4", "")
        record["Specification Sheet"] = raw_specs.get("Specification Sheet", "")
        record["MARKETING_DESCRIPTION"] = raw_specs.get("MARKETING_DESCRIPTION") or raw_specs.get("Marketing Description") or ""
        record["Product Name"] = raw_specs.get("Product Name") or attrs.item_type or descriptions.get("product_title", "")

        # Item Features 1..11
        features = raw_specs.get("features") or getattr(attrs, "features", None) or []
        for i in range(1, 12):
            feat_val = raw_specs.get(f"ITEM_FEATURES_{i}") or (features[i - 1] if i - 1 < len(features) else "")
            record[f"ITEM_FEATURES_{i}"] = feat_val

        # Multi-Channel Descriptions
        record["INVOICE_DESC"] = descriptions.get("invoice_desc", "")
        record["MOBILE_DESC"] = descriptions.get("mobile_desc", "")
        record["SHORT_DESC"] = descriptions.get("short_desc", "")
        record["LONG_DESC1"] = descriptions.get("long_desc", "")
        record["RETAIL_DESC"] = descriptions.get("product_title", "")

        # Default Metadata
        record["Actual Image (Yes/No)"] = "Yes" if record["Product Image"] else "No"
        record["Selling Qty"] = "1"
        record["Selling UOM"] = "EA"
        record["Country Of Origin"] = "US"
        record["Discontinued"] = "No"

        # Combine spec_sections and top-level extracted attributes for fixed slot mapping
        combined_specs = {}
        spec_sec = raw_specs.get("spec_sections") or getattr(attrs, "spec_sections", None) or {}
        if isinstance(spec_sec, dict):
            combined_specs.update(spec_sec)

        if attrs.voltage and "Voltage Rating" not in combined_specs and "Voltage" not in combined_specs:
            combined_specs["Voltage Rating"] = attrs.voltage
        if getattr(attrs, "amperage", None) and "Amperage Rating" not in combined_specs and "Amperage" not in combined_specs:
            combined_specs["Amperage Rating"] = getattr(attrs, "amperage")
        if attrs.dimensions and "Size" not in combined_specs and "Dimensions" not in combined_specs:
            combined_specs["Size"] = attrs.dimensions
        if attrs.mounting and "Mounting Type" not in combined_specs and "Mounting" not in combined_specs:
            combined_specs["Mounting Type"] = attrs.mounting
        if attrs.material and "Material" not in combined_specs:
            combined_specs["Material"] = attrs.material

        for k, v in raw_specs.items():
            if k not in combined_specs and k != "spec_sections":
                combined_specs[k] = v

        AttributeSlotRegistry.map_specs_to_fixed_slots(
            spec_dict=combined_specs,
            item_type=attrs.item_type or "",
            record=record,
        )

        return record

        # Additional raw_specs not already mapped
        already_mapped = {"FlowRate", "ConnectionType", "PressureRating", "Finish", "Grit", "ArborSize", "Amperage", "SoundLevel"}
        for k, v in raw_specs.items():
            if k not in already_mapped and slot <= 50:
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
        if "FlowRate" in raw_specs and feat_idx <= 20:
            record[f"ITEM_FEATURES_{feat_idx}"] = f"Flow rate: {raw_specs['FlowRate']}"
            feat_idx += 1
        if "ConnectionType" in raw_specs and feat_idx <= 20:
            record[f"ITEM_FEATURES_{feat_idx}"] = f"Standard {raw_specs['ConnectionType']} connection"
            feat_idx += 1

        return record


def generate_252_column_record(
    raw_req: EnrichmentRequest,
    canonical_brand: str,
    attrs: ExtractedAttributes,
    descriptions: dict[str, str],
    confidence: float = 1.0,
    canonical_manufacturer: Optional[str] = None,
) -> dict[str, Any]:
    return SchemaMapper.map_to_252_column_record(
        raw_req=raw_req,
        canonical_brand=canonical_brand,
        attrs=attrs,
        descriptions=descriptions,
        confidence=confidence,
        canonical_manufacturer=canonical_manufacturer,
    )


def export_dataframe_to_252_csv(df: pd.DataFrame | list[dict[str, Any]]) -> str:
    """Export DataFrame or list of dictionary records as a strictly formatted, CSV-safe 252-column text payload."""
    if isinstance(df, list):
        df = pd.DataFrame(df)
    output = io.StringIO()
    aligned_df = df.reindex(columns=DELIVERY_HEADERS, fill_value="")
    aligned_df.to_csv(output, index=False, quoting=csv.QUOTE_MINIMAL)
    return output.getvalue()
