from __future__ import annotations

import re
from typing import Any, Optional

from app.core.sanitizer import clean_placeholders
from app.data.loader import master_data_loader
from app.data.master_repository import master_data_repository

# Standard UOM pattern with lookbehinds/lookaheads to prevent double spacing
UOM_REGEX = re.compile(
    r"(?<=\d)\s*(in(?:ches|ch)?|\"|ft|feet|foot|\'|v(?:olts?|olt)?|a(?:mps?|mperage)?|w(?:atts?|att)?|hz|rpm|dba?|mm|cm|m|lbs?|oz|pk|pc|ea)(?=\b|\s|$)",
    re.IGNORECASE,
)

# Standard decimal pattern e.g., 50.25, 0.5, .75
DECIMAL_REGEX = re.compile(r"(\d+)?\.(\d+)")

# Tiered Progressive Abbreviation Rules for Invoice Descriptions (<= 40 chars)
INVOICE_TIER_1_MATERIALS_AND_MOUNTING: list[tuple[str, str]] = [
    ("STAINLESS STEEL", "SST"),
    ("BUILT-IN", "BLTLN"),
    ("BUILT IN", "BLTLN"),
    ("UNDER-COUNTER", "UNDRCTR"),
    ("UNDER COUNTER", "UNDRCTR"),
    ("FREESTANDING", "FRSTD"),
    ("FREE STANDING", "FRSTD"),
    ("CARBON STEEL", "CS"),
    ("ALUMINUM", "ALUM"),
    ("HIGH SPEED STEEL", "HSS"),
]

INVOICE_TIER_2_ITEMS_AND_ACCESSORIES: list[tuple[str, str]] = [
    ("DISHWASHER", "DISHWSHR"),
    ("RECIPROCATING", "RECIP"),
    ("SANDING BELT", "SND BELT"),
    ("CUT-OFF DISC", "CUT OFF DISC"),
    ("CUT OFF DISC", "CUT OFF DISC"),
    ("ABRASIVE DISC", "ABR DISC"),
    ("MEASURING TAPE", "TAPE"),
    ("SAFETY GLASSES", "SAFETY GLS"),
    ("CIRCULAR SAW", "CIRC SAW"),
]

INVOICE_TIER_3_SPECS_AND_PACKAGING: list[tuple[str, str]] = [
    ("PACKAGE", "PK"),
    ("PACK", "PK"),
    ("PIECES", "PC"),
    ("PIECE", "PC"),
    ("DIAMETER", "DIA"),
    ("MOUNTING", "MNT"),
    ("DIMENSION", "DIM"),
    ("DIMENSIONS", "DIM"),
    ("COMMERCIAL", "COMM"),
    ("INDUSTRIAL", "IND"),
    ("STANDARD", "STD"),
    ("PREMIUM", "PREM"),
    ("INCHES", "IN"),
    ("INCH", "IN"),
    ("VOLTS", "V"),
    ("VOLT", "V"),
    ("AMPERAGE", "A"),
    ("AMPS", "A"),
    ("AMP", "A"),
    ("HERTZ", "HZ"),
    ("DECIBELS", "DBA"),
    ("DECIBEL", "DBA"),
]

# Combined lookup for backward compatibility
INVOICE_ABBREVIATIONS: list[tuple[str, str]] = (
    INVOICE_TIER_1_MATERIALS_AND_MOUNTING
    + INVOICE_TIER_2_ITEMS_AND_ACCESSORIES
    + INVOICE_TIER_3_SPECS_AND_PACKAGING
)


class CatalogGuardrailEngine:
    """Production catalog deterministic guardrail engine enforcing Unilog standard rules."""

    @staticmethod
    def enforce_uom_spacing(text: Optional[str]) -> str:
        """Ensure standard spacing and casing between numeric values and UOMs (e.g. '24in' -> '24 in', '120v' -> '120 V')."""
        if not text:
            return ""

        uom_standards = master_data_repository.uom_standards or master_data_loader.load_uom_standards()

        def _replace_uom(match: re.Match) -> str:
            uom_raw = match.group(1).lower()
            canonical_uom = uom_standards.get(uom_raw, uom_raw)
            return f" {canonical_uom}"

        # Replace glued UOMs with spaced standard casing
        result = UOM_REGEX.sub(_replace_uom, text)

        # Normalize double spaces
        result = re.sub(r"\s+", " ", result).strip()
        return result

    @staticmethod
    def decimal_to_fraction(text: Optional[str], fraction_map: Optional[dict[float, str]] = None) -> str:
        """Convert decimal measurements into standard compound fractions (e.g. '50.25 in' -> '50-1/4 in', '0.5 in' -> '1/2 in')."""
        if not text:
            return ""

        if fraction_map is None:
            fraction_map = master_data_repository.decimal_fractions or master_data_loader.load_decimal_fractions()

        def _replace_decimal(match: re.Match) -> str:
            whole_str = match.group(1)
            dec_str = match.group(2)
            full_val = float(match.group(0))

            whole_val = int(whole_str) if whole_str else 0
            decimal_val = round(full_val - whole_val, 5)

            # Exact or close lookup in fraction map
            matched_fraction = None
            if decimal_val in fraction_map:
                matched_fraction = fraction_map[decimal_val]
            else:
                for k, v in fraction_map.items():
                    if abs(k - decimal_val) < 0.005:
                        matched_fraction = v
                        break

            if matched_fraction:
                if whole_val > 0:
                    return f"{whole_val}-{matched_fraction}"
                return matched_fraction

            return match.group(0)

        dimension_decimal_regex = re.compile(
            r"(\d+)?\.(\d+)(?=\s*(?:in|inch|inches|\"|ft|mm|cm|x|\b))",
            re.IGNORECASE,
        )

        result = dimension_decimal_regex.sub(_replace_decimal, text)
        result = re.sub(r"\s+", " ", result).strip()
        return result

    @staticmethod
    def format_invoice_desc(text: Optional[str]) -> str:
        """Format and progressively compress description adhering strictly to Unilog rules:

        1. ALL CAPS
        2. Standard abbreviations (STAINLESS STEEL -> SST, BUILT-IN -> BLTLN, PACKAGE -> PK)
        3. Strictly <= 40 characters
        4. Deterministic progressive compression (NO blind truncation)
        """
        if not text:
            return ""

        # Step 1: Base uppercase and clean spaces
        cleaned = clean_placeholders(text) or text
        formatted = re.sub(r"\s+", " ", cleaned).strip().upper()

        # Step 2: Standard Invoice Taxonomy Abbreviations (Tier 1: Materials & Mountings & Pack)
        for full_term, abbr in INVOICE_TIER_1_MATERIALS_AND_MOUNTING:
            if full_term in formatted:
                formatted = formatted.replace(full_term, abbr)
                formatted = re.sub(r"\s+", " ", formatted).strip()

        if "PACKAGE" in formatted:
            formatted = formatted.replace("PACKAGE", "PK")
            formatted = re.sub(r"\s+", " ", formatted).strip()

        if len(formatted) <= 40:
            return formatted

        # Step 3: Progressive Compression - Tier 2 (Item Types)
        for full_term, abbr in INVOICE_TIER_2_ITEMS_AND_ACCESSORIES:
            if len(formatted) <= 40:
                break
            if full_term in formatted:
                formatted = formatted.replace(full_term, abbr)
                formatted = re.sub(r"\s+", " ", formatted).strip()

        # Step 4: Progressive Compression - Tier 3 (Specs & Packaging)
        if len(formatted) > 40:
            for full_term, abbr in INVOICE_TIER_3_SPECS_AND_PACKAGING:
                if len(formatted) <= 40:
                    break
                if full_term in formatted:
                    formatted = formatted.replace(full_term, abbr)
                    formatted = re.sub(r"\s+", " ", formatted).strip()

        # Step 5: Remove non-critical connectors and filler words
        if len(formatted) > 40:
            fillers = [" WITH", " FOR", " AND", " THE", " PREMIUM", " STANDARD", " COMMERCIAL"]
            for f in fillers:
                if len(formatted) <= 40:
                    break
                formatted = formatted.replace(f, "")
                formatted = re.sub(r"\s+", " ", formatted).strip()

        # Step 6: Safe Boundary Word Trim (never chop mid-word)
        if len(formatted) > 40:
            clipped = formatted[:40]
            if " " in clipped:
                formatted = clipped.rsplit(" ", 1)[0].strip()
            else:
                formatted = clipped

        return formatted.upper()

    @staticmethod
    def validate_numeric_sanity(field_name: str, value: Any) -> bool:
        """Verify numeric specifications fall within realistic physical boundaries."""
        if value is None:
            return True
        val_str = str(value)
        num_match = re.search(r"[-+]?(?:\d*\.\d+|\d+)", val_str)
        if not num_match:
            return True
        try:
            num = float(num_match.group(0))
            f_lower = field_name.lower()
            if "voltage" in f_lower:
                return 0 < num <= 1000
            if "amperage" in f_lower or "amp" in f_lower:
                return 0 < num <= 2000
            if "dimension" in f_lower or "width" in f_lower or "depth" in f_lower or "height" in f_lower:
                return 0 < num <= 1000
            if "sound" in f_lower or "dba" in f_lower:
                return 0 <= num <= 150
            return num >= 0
        except ValueError:
            return True


# Backward-compatible module-level functions
def enforce_uom_spacing(text: Optional[str]) -> str:
    return CatalogGuardrailEngine.enforce_uom_spacing(text)


def decimal_to_fraction(text: Optional[str], fraction_map: Optional[dict[float, str]] = None) -> str:
    return CatalogGuardrailEngine.decimal_to_fraction(text, fraction_map)


def format_invoice_desc(text: Optional[str]) -> str:
    return CatalogGuardrailEngine.format_invoice_desc(text)


def format_mobile_desc(
    brand: Optional[str],
    item_type: Optional[str],
    series: Optional[str],
    mpn: str,
    attrs_summary: Optional[str] = None,
) -> str:
    """Generate MOBILE_DESC calibrated strictly to the 60-80 character bracket."""
    clean_brand = brand.strip() if brand else "UNASSIGNED"
    clean_type = item_type.strip() if item_type else "Product"
    clean_mpn = mpn.strip()

    components = [clean_brand, clean_type]
    if series:
        components.append(series.strip())
    components.append(clean_mpn)

    base = ", ".join(components)

    if attrs_summary and len(base) + len(attrs_summary) + 2 <= 78:
        base += f", {attrs_summary}"

    # Pad or calibrate to 60-80 chars
    if len(base) < 60:
        padding = f" - Industrial Grade {clean_type}"
        base = (base + padding)[:78]
    elif len(base) > 80:
        base = base[:80].rsplit(" ", 1)[0]

    return base
