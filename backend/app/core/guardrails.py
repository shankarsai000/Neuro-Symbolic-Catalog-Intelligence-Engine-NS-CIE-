from __future__ import annotations

import re
from typing import Any

from app.data.loader import (
    FALLBACK_DECIMAL_FRACTIONS,
    FALLBACK_UOM_STANDARDS,
    master_data_loader,
)

# Canonical formatting map for standard units
CANONICAL_UOM_FORMATS: dict[str, str] = {
    "in": "in",
    "inch": "in",
    "inches": "in",
    "ft": "ft",
    "foot": "ft",
    "feet": "ft",
    "yd": "yd",
    "yard": "yd",
    "yards": "yd",
    "mm": "mm",
    "cm": "cm",
    "m": "m",
    "v": "V",
    "volt": "V",
    "volts": "V",
    "kv": "kV",
    "a": "A",
    "amp": "A",
    "amps": "A",
    "ampere": "A",
    "amperes": "A",
    "ma": "mA",
    "w": "W",
    "watt": "W",
    "watts": "W",
    "kw": "kW",
    "hp": "HP",
    "hz": "Hz",
    "khz": "kHz",
    "mhz": "MHz",
    "ghz": "GHz",
    "rpm": "RPM",
    "dba": "dBA",
    "db": "dB",
    "psi": "psi",
    "oz": "oz",
    "lb": "lb",
    "lbs": "lb",
    "kg": "kg",
    "g": "g",
    "deg": "deg",
    "gal": "gal",
    "gpm": "GPM",
    "cfm": "CFM",
}

# Regex to detect numbers immediately glued to unit names (e.g. 24in, 120v, 15a, 47dba)
# Matches numbers (integers, decimals, or fraction components) followed by unit symbols
UOM_ATTACHED_REGEX = re.compile(
    r"(?<![A-Za-z0-9_])"  # Left boundary: not part of a word/alphanumeric code
    r"(\d+(?:\.\d+)?|\d+-\d+/\d+|\d+/\d+)"  # Group 1: Numeric value
    r"(in(?:ch(?:es)?)?|ft|feet|foot|yd|yards?|mm|cm|m|v|volts?|kv|a|amps?|ampere?s?|ma|w|watts?|kw|hp|hz|khz|mhz|ghz|rpm|dba|db|psi|oz|lbs?|kg|g|deg|gal|gpm|cfm)"  # Group 2: Unit name
    r"(?![A-Za-z0-9_])",  # Right boundary: not part of a trailing identifier
    re.IGNORECASE,
)

# Regex to detect floating point numbers followed by inch designations
INCH_DECIMAL_REGEX = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(\d*)\.(\d+)"  # Group 1: whole part, Group 2: decimal part
    r"\s*(in(?:ch(?:es)?)?|\"|in\.)"  # Group 3: inch unit
    r"(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


def enforce_uom_spacing(text: Any) -> str:
    """Enforce standard spacing and canonical casing between numbers and units.

    Examples:
        '24in' -> '24 in'
        '24inches' -> '24 in'
        '120v' -> '120 V'
        '15a' -> '15 A'
        '47dba' -> '47 dBA'
        '50.25in' -> '50.25 in'

    Args:
        text: Input string or value to format.

    Returns:
        Formatted string with enforced unit spacing and canonical casing.
    """
    if text is None:
        return ""

    if not isinstance(text, str):
        text = str(text)

    def _replace_uom(match: re.Match[str]) -> str:
        value = match.group(1)
        raw_unit = match.group(2).lower()
        canonical_unit = CANONICAL_UOM_FORMATS.get(raw_unit, raw_unit)
        return f"{value} {canonical_unit}"

    return UOM_ATTACHED_REGEX.sub(_replace_uom, text)


def decimal_to_fraction(
    text: Any, fraction_map: dict[Any, str] | None = None
) -> str:
    """Find decimal numbers followed by inch unit and replace with compound fraction.

    Examples:
        '50.25 in' -> '50-1/4 in'
        '0.5 in'   -> '1/2 in'
        '.75 in'   -> '3/4 in'

    Args:
        text: Input string to process.
        fraction_map: Optional dictionary mapping floats/strings to fraction strings.
                     If None, loads standard lookup from master_data_loader.

    Returns:
        String with inch decimals converted to compound fractions.
    """
    if text is None:
        return ""

    if not isinstance(text, str):
        text = str(text)

    if fraction_map is None:
        fraction_map = master_data_loader.load_decimal_fractions()

    # Pre-process fraction map keys for fast float lookup
    normalized_map: dict[float, str] = {}
    for k, v in fraction_map.items():
        try:
            normalized_map[round(float(k), 5)] = str(v).strip()
        except (ValueError, TypeError):
            continue

    def _replace_decimal(match: re.Match[str]) -> str:
        whole_str = match.group(1).strip()
        dec_str = match.group(2).strip()
        unit = match.group(3).lower()

        # Canonicalize inch unit to 'in'
        canonical_unit = "in"

        # Calculate decimal value (e.g. 0.25)
        decimal_val = round(float(f"0.{dec_str}"), 5)
        fraction_str = normalized_map.get(decimal_val)

        # If not found directly, try rounding to 4, 3, 2 decimal places
        if fraction_str is None:
            for precision in (4, 3, 2):
                rounded_val = round(decimal_val, precision)
                if rounded_val in normalized_map:
                    fraction_str = normalized_map[rounded_val]
                    break

        if fraction_str:
            whole_num = int(whole_str) if whole_str and whole_str.isdigit() else 0
            if whole_num > 0:
                return f"{whole_num}-{fraction_str} {canonical_unit}"
            return f"{fraction_str} {canonical_unit}"

        # If fraction cannot be resolved, return original with standard unit spacing
        whole_part = whole_str if whole_str else "0"
        return f"{whole_part}.{dec_str} {canonical_unit}"

    return INCH_DECIMAL_REGEX.sub(_replace_decimal, text)


def format_invoice_desc(text: Any) -> str:
    """Format invoice description according to Unilog standards.

    Enforces:
    1. ALL CAPS text.
    2. Strict 40-character maximum length limit.

    Args:
        text: Input string.

    Returns:
        Formatted uppercase string trimmed to max 40 characters.
    """
    if text is None:
        return ""

    if not isinstance(text, str):
        text = str(text)

    clean_text = text.strip()
    return clean_text[:40].upper()
