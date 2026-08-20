"""
Unilog 252-Column Delivery Schema Contract
Authoritative, immutable schema definition for NS-CIE v2.1/v2.2.
Zero product-specific hardcoding permitted.
"""

from typing import Dict, List, Tuple, Any
from app.core.delivery import DELIVERY_HEADERS

UNILOG_252_COLUMNS: Tuple[str, ...] = tuple(DELIVERY_HEADERS)

assert len(UNILOG_252_COLUMNS) == 252, f"Schema mismatch: Expected 252 columns, got {len(UNILOG_252_COLUMNS)}"


def validate_252_column_schema(columns: List[str]) -> Tuple[bool, str]:
    if len(columns) != 252:
        return False, f"Invalid column count: {len(columns)} (expected 252)"
    for i, (expected, actual) in enumerate(zip(UNILOG_252_COLUMNS, columns)):
        if expected != actual:
            return False, f"Mismatch at index {i}: expected '{expected}', got '{actual}'"
    return True, "Schema is exact 252-column compliant"


def format_252_delivery_record(extracted_facts: Dict[str, Any]) -> Dict[str, Any]:
    """
    Project extracted facts into a complete 252-column dictionary.
    Guarantees mandatory schema fallback values for required fields.
    """
    mpn = str(extracted_facts.get("Mfg_Part_Num") or extracted_facts.get("mpn") or extracted_facts.get("PART_NUMBER") or "").strip()
    part_desc = str(extracted_facts.get("Part_Desc") or extracted_facts.get("SHORT_DESC") or mpn or "Commercial Product").strip()
    part_manuf = str(extracted_facts.get("Part_Manuf") or extracted_facts.get("MANUFACTURER_NAME") or "Commercial Manufacturer").strip()
    brand = str(extracted_facts.get("BRAND_NAME") or extracted_facts.get("Unilog_Brand") or part_manuf or "Commercial Brand").strip()
    product_name = str(extracted_facts.get("Product Name") or extracted_facts.get("PRODUCT_NAME") or part_desc[:30]).strip()

    record: Dict[str, Any] = {}
    for col in UNILOG_252_COLUMNS:
        val = extracted_facts.get(col, "")
        record[col] = "" if val is None else str(val)

    # Generic Schema Guarantee for mandatory delivery fields
    if "PART_NUMBER" in record and not record["PART_NUMBER"]:
        record["PART_NUMBER"] = mpn
    if "Mfg_Part_Num" in record and not record["Mfg_Part_Num"]:
        record["Mfg_Part_Num"] = mpn
    if "MANUFACTURER_PART_NUMBER" in record and not record["MANUFACTURER_PART_NUMBER"]:
        record["MANUFACTURER_PART_NUMBER"] = mpn
    if "MANUFACTURER_NAME" in record and not record["MANUFACTURER_NAME"]:
        record["MANUFACTURER_NAME"] = part_manuf
    if "BRAND_NAME" in record and not record["BRAND_NAME"]:
        record["BRAND_NAME"] = brand
    if "Product Name" in record and not record["Product Name"]:
        record["Product Name"] = product_name
    if "INVOICE_DESC" in record and not record["INVOICE_DESC"]:
        record["INVOICE_DESC"] = f"{brand[:8]} {product_name[:15]} {mpn}".upper().strip()[:40]
    if "MOBILE_DESC" in record and not record["MOBILE_DESC"]:
        record["MOBILE_DESC"] = f"{brand} {product_name} {mpn}".strip()[:60]
    if "Actual Image (Yes/No)" in record and not record["Actual Image (Yes/No)"]:
        record["Actual Image (Yes/No)"] = "No"

    return record
