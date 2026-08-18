from __future__ import annotations

import pytest

from app.agents.resolver import resolve_canonical_brand
from app.agents.manufacturer_sourcing import source_cache
from app.agents.scraper import fetch_manufacturer_context


def test_resolve_canonical_brand_fuzzy_matching():
    assert resolve_canonical_brand("frigid air") == "FRIGIDAIRE®"
    assert resolve_canonical_brand("Freud Inc (2435)") == "FREUD®"
    assert resolve_canonical_brand("Milwaukee Accessory (4031)") == "MILWAUKEE®"
    assert resolve_canonical_brand("Mirka Abrasives Inc (MIRUS)") == "MIRKA®"
    assert resolve_canonical_brand("Whirlpool Corporation") == "WHIRLPOOL®"
    assert resolve_canonical_brand("Unbranded Custom Widget Co") == "Unbranded Custom Widget"
    assert resolve_canonical_brand(None) == ""
    assert resolve_canonical_brand("-- Unbranded --") == ""


@pytest.mark.anyio
async def test_fetch_manufacturer_context_and_caching():
    brand = "FRIGIDAIRE®"
    mpn = "PDSH4816AF"

    # Pre-seed cache to verify cache lookup & retrieval contract
    source_cache.set(brand, mpn, {
        "brand": brand,
        "mpn": mpn,
        "domain": "www.frigidaire.com",
        "source_url": "https://www.frigidaire.com/products/pdsh4816af",
        "source_type": "manufacturer_official_html",
        "http_status": 200,
        "content_hash": "hash123",
        "extracted_text": "Frigidaire Dishwasher PDSH4816AF 120 V Stainless Steel 24 in",
        "evidence_snippets": {"voltage": {"value": "120 V", "confidence": 1.0}},
        "provenance_score": 1.0,
        "retrieved_at": "2026-08-18T12:00:00Z",
    })

    # First fetch (Cache HIT)
    context_1 = await fetch_manufacturer_context(brand, mpn)
    assert context_1 != ""
    assert "Frigidaire" in context_1
    assert "PDSH4816AF" in context_1

    # Second fetch returns identical context
    context_2 = await fetch_manufacturer_context(brand, mpn)
    assert context_2 == context_1
