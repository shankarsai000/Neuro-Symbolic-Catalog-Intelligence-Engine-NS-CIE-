from __future__ import annotations

import logging
from typing import Optional
from app.agents.manufacturer_sourcing import fetch_official_manufacturer_specs, source_cache

logger = logging.getLogger(__name__)


async def fetch_manufacturer_context(canonical_brand: str, mpn: str) -> str:
    """Retrieve official manufacturer product specifications for extraction grounding.

    Zero simulation: Connects strictly to official manufacturer domains over HTTPS
    with domain allowlist, redirect verification, and two-tier caching.

    Args:
        canonical_brand: Canonical legal manufacturer/brand name.
        mpn: Manufacturer Part Number.

    Returns:
        Clean technical text extract from official source, or empty string if offline/unreachable.
    """
    if not canonical_brand and not mpn:
        return ""

    result = await fetch_official_manufacturer_specs(canonical_brand, mpn)
    return result.extracted_text
