from __future__ import annotations

import re
from typing import Optional
from rapidfuzz import fuzz, process, utils

from app.core.sanitizer import clean_placeholders

# Master list representing UniCat_Manufacturer_and_Brand_List.xlsx legal entity names
MASTER_CANONICAL_BRANDS: list[str] = [
    "FRIGIDAIRE®",
    "WHIRLPOOL®",
    "KOHLER®",
    "GE APPLIANCES",
    "MILWAUKEE®",
    "3M™",
    "FREUD®",
    "DIABLO®",
    "MIRKA®",
    "DEWALT®",
    "RHEEM®",
    "BOSCH®",
    "MAKITA®",
    "CRAFTSMAN®",
    "DELTA®",
    "MOEN®",
    "SCHNEIDER ELECTRIC™",
    "EATON®",
    "SIEMENS®",
    "SQUARE D™",
]

# Supplier code & noise pattern (e.g. '(2435)', '(MIRUS)', 'LLC', 'Inc', 'Co')
SUPPLIER_NOISE_REGEX = re.compile(
    r"\s*(?:\(\w+\)|LLC|Inc\.?|Corp\.?|Co\.?|Supply|Accessory)\b",
    re.IGNORECASE,
)


def resolve_canonical_brand(raw_brand: Optional[str], score_cutoff: float = 80.0) -> str:
    """Fuzzy-match raw or supplier brand names to official Unilog canonical entity standards.

    Examples:
        'frigid air' -> 'FRIGIDAIRE®'
        'Freud Inc (2435)' -> 'FREUD®'
        'Milwaukee Accessory (4031)' -> 'MILWAUKEE®'
        'Mirka Abrasives Inc (MIRUS)' -> 'MIRKA®'
        'Unknown Custom Tools Co' -> 'Unknown Custom Tools'

    Args:
        raw_brand: Raw manufacturer or brand string from supplier.
        score_cutoff: Minimum RapidFuzz match similarity score (0-100). Default 80.0.

    Returns:
        Canonical legal brand name if matched, else sanitized title-cased brand string.
    """
    if not raw_brand:
        return ""

    sanitized = clean_placeholders(raw_brand)
    if not sanitized:
        return ""

    # Clean out parenthesized supplier codes and corporate entity suffix noise
    query = SUPPLIER_NOISE_REGEX.sub("", sanitized).strip()
    if not query:
        query = sanitized

    # Direct / token fuzzy match with standard text preprocessor
    best_match = process.extractOne(
        query,
        MASTER_CANONICAL_BRANDS,
        processor=utils.default_process,
        scorer=fuzz.WRatio,
        score_cutoff=score_cutoff,
    )

    if best_match:
        matched_brand, score, _ = best_match
        return matched_brand

    # Fallback to token_set_ratio with default_process
    token_match = process.extractOne(
        query,
        MASTER_CANONICAL_BRANDS,
        processor=utils.default_process,
        scorer=fuzz.token_set_ratio,
        score_cutoff=score_cutoff,
    )

    if token_match:
        matched_brand, score, _ = token_match
        return matched_brand

    # If no high-confidence match found, return cleaned query
    return query.strip()
