from __future__ import annotations

import pytest
from app.agents.manufacturer_sourcing import (
    APPROVED_MANUFACTURER_DOMAINS,
    extract_evidence_snippets_from_text,
    extract_text_from_pdf_bytes,
    fetch_official_manufacturer_specs,
    is_url_allowed,
)


def test_domain_allowlist_validation():
    # Valid official domain with HTTPS
    assert is_url_allowed("https://www.frigidaire.com/products/pdsh4816af", "FRIGIDAIRE®") is True
    assert is_url_allowed("https://www.milwaukeetool.com/products/49-94-0013", "MILWAUKEE®") is True

    # Insecure HTTP rejected
    assert is_url_allowed("http://www.frigidaire.com/products/pdsh4816af", "FRIGIDAIRE®") is False

    # Unapproved 3rd party domain rejected
    assert is_url_allowed("https://www.randomsupplier.com/part123", "FRIGIDAIRE®") is False
    assert is_url_allowed("https://www.homedepot.com/p/12345", "FRIGIDAIRE®") is False


def test_evidence_snippets_extraction():
    sample_text = """
    Product Specifications:
    Operating Voltage: 120 V 60Hz 15 A
    Dimensions: 33-7/16 in H x 23-7/8 in W x 22-5/8 in D
    Material: Stainless Steel interior and door
    Mounting: Built-In Under-Counter Installation
    """
    snippets = extract_evidence_snippets_from_text(sample_text, "PDSH4816AF")
    assert "voltage" in snippets
    assert "dimensions" in snippets
    assert "material" in snippets
    assert "mounting" in snippets


@pytest.mark.asyncio
async def test_fetch_official_manufacturer_offline_safe():
    res = await fetch_official_manufacturer_specs("FRIGIDAIRE®", "PDSH4816AF")
    assert res.brand == "FRIGIDAIRE®"
    assert res.mpn == "PDSH4816AF"
    assert res.provenance_score > 0.0
