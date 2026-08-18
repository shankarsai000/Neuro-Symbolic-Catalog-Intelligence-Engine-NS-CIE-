from __future__ import annotations

import re
from typing import Optional
from app.core.sanitizer import clean_placeholders
from app.data.master_repository import master_data_repository

# Supplier code & noise pattern (e.g. '(2435)', '(MIRUS)', 'LLC', 'Inc', 'Co', 'Tools', 'Supply')
SUPPLIER_NOISE_REGEX = re.compile(
    r"\s*(?:\(\w+\)|LLC|Inc\.?|Corp\.?|Co\.?|Supply|Accessory|Tools?|Company|Products?)\b",
    re.IGNORECASE,
)


def resolve_canonical_brand(raw_brand: Optional[str], score_cutoff: float = 80.0) -> str:
    """Fuzzy-match raw or supplier brand names to official Unilog canonical entity standards.

    Driven entirely by the MasterDataRepository / BrandRepository without hardcoded production lists.

    Examples:
        'frigid air' -> 'FRIGIDAIRE®'
        'Freud Inc' -> 'FREUD®'
        'Milwaukee Accessory' -> 'MILWAUKEE®'
        'Mirka Abrasives' -> 'MIRKA®'
        'Unknown Custom Tools Co' -> 'Unknown Custom Tools' (unresolved)

    Args:
        raw_brand: Raw manufacturer or brand string from supplier.
        score_cutoff: Minimum similarity score cutoff (0-100). Default 80.0.

    Returns:
        Canonical legal brand name if matched with confidence >= score_cutoff,
        else cleaned unforced query string.
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

    # Query BrandRepository dynamically from MasterDataRepository
    canonical, score = master_data_repository.resolve_canonical_brand(
        query, score_cutoff=score_cutoff
    )

    if score > 0.0:
        return canonical

    # If no high-confidence match found, return unforced query
    return query.strip()
