from __future__ import annotations

import pytest

from app.agents.resolver import resolve_canonical_brand
from app.agents.scraper import MFR_CONTEXT_CACHE, fetch_manufacturer_context


def test_resolve_canonical_brand_fuzzy_matching():
    assert resolve_canonical_brand("frigid air") == "FRIGIDAIRE®"
    assert resolve_canonical_brand("Freud Inc (2435)") == "FREUD®"
    assert resolve_canonical_brand("Milwaukee Accessory (4031)") == "MILWAUKEE®"
    assert resolve_canonical_brand("Mirka Abrasives Inc (MIRUS)") == "MIRKA®"
    assert resolve_canonical_brand("Whirlpool Corporation") == "WHIRLPOOL®"
    assert resolve_canonical_brand("3MABR-7100075678") == "3M™"
    assert resolve_canonical_brand("Unbranded Custom Widget Co") == "Unbranded Custom Widget"
    assert resolve_canonical_brand(None) == ""
    assert resolve_canonical_brand("-- Unbranded --") == ""


@pytest.mark.anyio
async def test_fetch_manufacturer_context_and_caching():
    brand = "FRIGIDAIRE®"
    mpn = "PDSH4816AF"
    cache_key = f"{brand}_{mpn}".strip().lower()

    # Clear cache entry if present
    MFR_CONTEXT_CACHE.pop(cache_key, None)

    # First fetch (Cache MISS)
    context_1 = await fetch_manufacturer_context(brand, mpn)
    assert context_1 != ""
    assert "FRIGIDAIRE" in context_1
    assert "PDSH4816AF" in context_1
    assert cache_key in MFR_CONTEXT_CACHE

    # Second fetch (Cache HIT)
    context_2 = await fetch_manufacturer_context(brand, mpn)
    assert context_2 == context_1
