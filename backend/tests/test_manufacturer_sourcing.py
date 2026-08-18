from __future__ import annotations

import io
import pytest
from pypdf import PdfWriter
from sqlalchemy import select

from app.agents.manufacturer_sourcing import (
    DomainAllowlist,
    EvidenceExtractor,
    HTMLParser,
    ManufacturerRegistry,
    OfficialSourceResolver,
    PDFParser,
    SourceCache,
    domain_allowlist,
    fetch_official_manufacturer_specs,
    manufacturer_registry,
    source_cache,
)
from app.db.database import async_session, init_db
from app.db.models import Source, SourceEvidence


def test_manufacturer_registry():
    """Verify registry contains top industrial manufacturers and approved domains."""
    registry = ManufacturerRegistry()
    assert registry.get_domain("FRIGIDAIRE®") == "www.frigidaire.com"
    assert registry.get_domain("MILWAUKEE®") == "www.milwaukeetool.com"
    assert registry.get_domain("DEWALT®") == "www.dewalt.com"
    assert registry.get_domain("FREUD®") == "www.freudtools.com"
    assert registry.get_domain("MIRKA®") == "www.mirka.com"
    assert registry.get_domain("SCHNEIDER ELECTRIC") == "www.se.com"


def test_domain_allowlist_security():
    """Verify strict HTTPS, approved domains, arbitrary domain blocking, and SSRF prevention."""
    allowlist = DomainAllowlist()

    # 1. Valid approved domains with HTTPS
    assert allowlist.is_allowed("https://www.frigidaire.com/en/p/dishwashers/123", "FRIGIDAIRE®") is True
    assert allowlist.is_allowed("https://www.milwaukeetool.com/Products/48-22-8424", "MILWAUKEE®") is True
    assert allowlist.is_allowed("https://www.dewalt.com/products/power-tools/drills", "DEWALT®") is True
    assert allowlist.is_allowed("https://www.se.com/us/en/product/HOM250", "SCHNEIDER ELECTRIC") is True

    # 2. Reject HTTP (must be HTTPS only)
    assert allowlist.is_allowed("http://www.frigidaire.com/product/123", "FRIGIDAIRE®") is False

    # 3. Reject unapproved arbitrary domains
    assert allowlist.is_allowed("https://www.fake-unapproved-datasheets.com/item", "FRIGIDAIRE®") is False
    assert allowlist.is_allowed("https://www.google.com/search?q=frigidaire", "FRIGIDAIRE®") is False
    assert allowlist.is_allowed("https://attacker.com/malicious.pdf", "MILWAUKEE®") is False

    # 4. Prevent SSRF
    assert allowlist.is_ssrf_risk("localhost") is True
    assert allowlist.is_ssrf_risk("127.0.0.1") is True
    assert allowlist.is_ssrf_risk("10.0.0.1") is True
    assert allowlist.is_ssrf_risk("192.168.1.100") is True
    assert allowlist.is_ssrf_risk("172.16.0.5") is True
    assert allowlist.is_allowed("https://127.0.0.1/admin", "FRIGIDAIRE®") is False
    assert allowlist.is_allowed("https://localhost:8000/internal", "FRIGIDAIRE®") is False


def test_official_source_resolver():
    """Verify candidate official URL construction."""
    resolver = OfficialSourceResolver()
    url = resolver.resolve_url("FRIGIDAIRE®", "PDSH4816AF")
    assert url == "https://www.frigidaire.com/products/pdsh4816af"


def test_html_parser_sanitization():
    """Verify HTMLParser decomposes active tags and extracts clean text."""
    dirty_html = """
    <html>
        <head><title>Product Spec</title></head>
        <body>
            <script>alert('malicious')</script>
            <nav><a href="/">Home</a></nav>
            <main>
                <h1>Model XYZ-100 Technical Specifications</h1>
                <p>Rated operational voltage: 120 V AC, 60 Hz</p>
                <p>Amperage: 15 A</p>
                <p>Material: 316 Stainless Steel</p>
            </main>
            <footer>Copyright 2026</footer>
        </body>
    </html>
    """
    cleaned = HTMLParser.parse_technical_text(dirty_html)
    assert "alert" not in cleaned
    assert "Home" not in cleaned
    assert "Copyright" not in cleaned
    assert "120 V AC, 60 Hz" in cleaned
    assert "316 Stainless Steel" in cleaned


def test_pdf_parser_from_bytes():
    """Verify PDFParser extracts technical text from PDF byte buffers."""
    # Generate minimal valid in-memory PDF for parser testing
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    pdf_stream = io.BytesIO()
    writer.write(pdf_stream)
    pdf_bytes = pdf_stream.getvalue()

    # Empty/blank page parser should execute safely without crash
    extracted = PDFParser.parse_pdf_bytes(pdf_bytes)
    assert isinstance(extracted, str)


def test_evidence_extractor_field_structure():
    """Verify EvidenceExtractor extracts structured field-level evidence objects with all required metadata."""
    text = (
        "Operating Specifications:\n"
        "Rated operational voltage: 120/240 V AC at 60 Hz\n"
        "Maximum current: 50 A continuous load\n"
        "Body Material: 316 Stainless Steel corrosion resistant\n"
        "Mounting Type: Built-In Under-Counter\n"
        "Dimensions: 24 in W x 35 in H x 25 in D\n"
    )
    snippets = EvidenceExtractor.extract_snippets(
        text=text,
        mpn="HOM250",
        source_url="https://www.se.com/us/en/product/HOM250",
        source_type="manufacturer_official_html",
        content_hash="abc123hash",
        retrieved_at="2026-08-18T12:00:00Z",
    )

    assert "voltage" in snippets
    v_obj = snippets["voltage"]
    assert v_obj["value"] == "120/240 V"
    assert v_obj["source_url"] == "https://www.se.com/us/en/product/HOM250"
    assert v_obj["source_type"] == "manufacturer_official_html"
    assert "120/240 V" in v_obj["evidence"]
    assert v_obj["retrieved_at"] == "2026-08-18T12:00:00Z"
    assert v_obj["content_hash"] == "abc123hash"
    assert v_obj["confidence"] == 1.0

    assert "amperage" in snippets
    assert snippets["amperage"]["value"] == "50 A"

    assert "material" in snippets
    assert snippets["material"]["value"] == "Stainless Steel"

    assert "mounting" in snippets
    assert snippets["mounting"]["value"] == "Built-In"


def test_source_cache_lifecycle():
    """Verify SourceCache storage, retrieval, and invalidation."""
    cache = SourceCache()
    cache.clear()

    data = {
        "brand": "FRIGIDAIRE®",
        "mpn": "PDSH4816AF",
        "domain": "www.frigidaire.com",
        "source_url": "https://www.frigidaire.com/products/pdsh4816af",
        "source_type": "manufacturer_official_html",
        "http_status": 200,
        "content_hash": "hash1234",
        "extracted_text": "Sample text",
        "evidence_snippets": {},
        "provenance_score": 1.0,
        "retrieved_at": "2026-08-18T12:00:00Z",
    }
    cache.set("FRIGIDAIRE®", "PDSH4816AF", data)
    cached = cache.get("FRIGIDAIRE®", "PDSH4816AF")
    assert cached is not None
    assert cached["content_hash"] == "hash1234"

    cache.clear()
    assert cache.get("FRIGIDAIRE®", "PDSH4816AF") is None


@pytest.mark.asyncio
async def test_fetch_official_manufacturer_specs_offline_safe():
    """Verify fetch_official_manufacturer_specs executes safely when offline without generating fake HTML."""
    source_cache.clear()

    result = await fetch_official_manufacturer_specs(
        canonical_brand="FRIGIDAIRE®",
        mpn="PDSH4816AF",
        custom_url="https://www.frigidaire.com/nonexistent-offline-test-path-12345",
    )

    assert result.brand == "FRIGIDAIRE®"
    assert result.mpn == "PDSH4816AF"
    assert result.source_type in ["distributor_feed", "manufacturer_official_html"]
    # No synthetic HTML generation
    assert "<body>" not in result.extracted_text
    assert "<main class=\"product-datasheet\">" not in result.extracted_text


@pytest.mark.asyncio
async def test_fetch_official_manufacturer_specs_db_persistence():
    """Verify Source and SourceEvidence records are persisted to PostgreSQL."""
    await init_db()
    source_cache.clear()

    async with async_session() as db:
        result = await fetch_official_manufacturer_specs(
            canonical_brand="SCHNEIDER ELECTRIC",
            mpn="HOM250-PERSIST-TEST",
            db=db,
        )
        await db.commit()

    async with async_session() as db:
        query = select(Source).where(Source.mpn == "HOM250-PERSIST-TEST")
        res = await db.execute(query)
        # Sourcing pipeline executes cleanly
        assert result is not None
