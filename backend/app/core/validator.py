"""
Semantic Input Validator & Placeholder Sanitizer
Validates raw 6-column supplier records and strips placeholder noise.
"""

from typing import Dict, Any, Tuple, Optional

PLACEHOLDER_STRINGS = {
    "-- unbranded --",
    "-- no unilog brand --",
    "-- no dib brand --",
    "n/a",
    "none",
    "null",
    "unknown",
    "undefined"
}

def sanitize_input_field(val: Optional[str]) -> Optional[str]:
    if val is None:
        return None
    cleaned = str(val).strip()
    if cleaned.lower() in PLACEHOLDER_STRINGS:
        return None
    return cleaned

def validate_supplier_input_row(row: Dict[str, Any]) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    sanitized = {
        "Mfg_Part_Num": sanitize_input_field(row.get("Mfg_Part_Num")),
        "Part_Desc": sanitize_input_field(row.get("Part_Desc")),
        "E1_Brand": sanitize_input_field(row.get("E1_Brand")),
        "Unilog_Brand": sanitize_input_field(row.get("Unilog_Brand")),
        "DIB_Brand": sanitize_input_field(row.get("DIB_Brand")),
        "Part_Manuf": sanitize_input_field(row.get("Part_Manuf")),
    }

    if not sanitized["Mfg_Part_Num"]:
        return False, "Missing or invalid Mfg_Part_Num", sanitized

    if not sanitized["Part_Desc"]:
        return False, "Missing or invalid Part_Desc", sanitized

    return True, None, sanitized
