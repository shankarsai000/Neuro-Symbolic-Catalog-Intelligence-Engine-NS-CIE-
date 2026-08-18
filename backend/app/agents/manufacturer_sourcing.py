from __future__ import annotations

import hashlib
import io
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

logger = logging.getLogger(__name__)

# Official Manufacturer Domain Allowlist (HTTPS only)
APPROVED_MANUFACTURER_DOMAINS: dict[str, str] = {
    "FRIGIDAIRE®": "www.frigidaire.com",
    "WHIRLPOOL®": "www.whirlpool.com",
    "MILWAUKEE®": "www.milwaukeetool.com",
    "DEWALT®": "www.dewalt.com",
    "FREUD®": "www.freudtools.com",
    "DIABLO®": "www.diablotools.com",
    "MIRKA®": "www.mirka.com",
    "SATCO®": "www.satco.com",
    "LEVITON®": "www.leviton.com",
    "FESTOOL®": "www.festoolusa.com",
    "SOUTHWIRE®": "www.southwire.com",
    "KICHLER®": "www.kichler.com",
    "MAKITA®": "www.makitausa.com",
    "3M™": "www.3m.com",
    "KREG®": "www.kregtool.com",
    "BOSCH®": "www.boschtools.com",
}

# In-Memory Cache for Sourced Documents
SOURCED_DOCS_CACHE: dict[str, dict[str, Any]] = {}


class SourcedEvidenceResult:
    def __init__(
        self,
        brand: str,
        mpn: str,
        domain: str,
        source_url: str,
        source_type: str,
        http_status: int,
        content_hash: str,
        extracted_text: str,
        evidence_snippets: dict[str, str],
        provenance_score: float,
        retrieved_at: str,
    ) -> None:
        self.brand = brand
        self.mpn = mpn
        self.domain = domain
        self.source_url = source_url
        self.source_type = source_type
        self.http_status = http_status
        self.content_hash = content_hash
        self.extracted_text = extracted_text
        self.evidence_snippets = evidence_snippets
        self.provenance_score = provenance_score
        self.retrieved_at = retrieved_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "brand": self.brand,
            "mpn": self.mpn,
            "domain": self.domain,
            "source_url": self.source_url,
            "source_type": self.source_type,
            "http_status": self.http_status,
            "content_hash": self.content_hash,
            "extracted_text": self.extracted_text,
            "evidence_snippets": self.evidence_snippets,
            "provenance_score": self.provenance_score,
            "retrieved_at": self.retrieved_at,
        }


def is_url_allowed(url: str, canonical_brand: str) -> bool:
    """Validate that the URL belongs to an approved official manufacturer domain with HTTPS."""
    try:
        parsed = urlparse(url)
        if parsed.scheme.lower() != "https":
            return False

        allowed_host = APPROVED_MANUFACTURER_DOMAINS.get(canonical_brand)
        if not allowed_host:
            return False

        host = parsed.netloc.lower()
        return host == allowed_host.lower() or host.endswith("." + allowed_host.lower().replace("www.", ""))
    except Exception:
        return False


def extract_text_from_pdf_bytes(pdf_bytes: bytes, max_pages: int = 3) -> str:
    """Extract plain text specifications from technical PDF datasheet bytes."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages_text = []
        for i in range(min(len(reader.pages), max_pages)):
            t = reader.pages[i].extract_text()
            if t:
                pages_text.append(t)
        return "\n".join(pages_text)
    except Exception as e:
        logger.warning(f"Error parsing PDF datasheet: {e}")
        return ""


def extract_evidence_snippets_from_text(text: str, mpn: str) -> dict[str, str]:
    """Parse key technical spec snippets from raw manufacturer text."""
    snippets: dict[str, str] = {}
    lines = text.split("\n")

    for line in lines:
        l_clean = line.strip()
        l_lower = l_clean.lower()
        if not l_clean:
            continue

        if "voltage" in l_lower or "120v" in l_lower or "120 v" in l_lower:
            snippets["voltage"] = l_clean[:120]
        if "dimension" in l_lower or "width" in l_lower or "depth" in l_lower or "diameter" in l_lower:
            snippets["dimensions"] = l_clean[:120]
        if "material" in l_lower or "stainless" in l_lower:
            snippets["material"] = l_clean[:120]
        if "mounting" in l_lower or "built-in" in l_lower or "freestanding" in l_lower:
            snippets["mounting"] = l_clean[:120]
        if "amperage" in l_lower or "amps" in l_lower:
            snippets["amperage"] = l_clean[:120]

    return snippets


async def fetch_official_manufacturer_specs(
    canonical_brand: str,
    mpn: str,
    custom_url: Optional[str] = None,
) -> SourcedEvidenceResult:
    """Retrieve and verify official manufacturer product context from approved domains."""
    cache_key = f"{canonical_brand}_{mpn}".upper()
    if cache_key in SOURCED_DOCS_CACHE:
        cached = SOURCED_DOCS_CACHE[cache_key]
        return SourcedEvidenceResult(**cached)

    domain = APPROVED_MANUFACTURER_DOMAINS.get(canonical_brand, "")
    target_url = custom_url or (f"https://{domain}/products/{mpn.lower()}" if domain else "")

    timestamp = datetime.now(timezone.utc).isoformat()

    # If domain is not in approved registry or URL fails validation
    if not domain or not target_url or not is_url_allowed(target_url, canonical_brand):
        result = SourcedEvidenceResult(
            brand=canonical_brand,
            mpn=mpn,
            domain="unapproved_or_offline",
            source_url="",
            source_type="distributor_feed",
            http_status=0,
            content_hash="0000000000000000",
            extracted_text="",
            evidence_snippets={},
            provenance_score=0.70,  # Base feed provenance
            retrieved_at=timestamp,
        )
        return result

    # Execute HTTP retrieval with timeouts, size limits and redirect verification
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NS-CIE Catalog Ingestion Engine/1.0",
        "Accept": "text/html,application/xhtml+xml,application/pdf",
    }

    try:
        async with httpx.AsyncClient(timeout=4.0, follow_redirects=True) as client:
            resp = await client.get(target_url, headers=headers)

            # Validate final redirect destination
            if not is_url_allowed(str(resp.url), canonical_brand):
                raise ValueError("Redirected to non-approved domain")

            # Check response size limit (5MB)
            content_len = len(resp.content)
            if content_len > 5 * 1024 * 1024:
                raise ValueError("Response payload exceeded 5MB size limit")

            content_type = resp.headers.get("content-type", "").lower()
            source_type = "pdf" if "pdf" in content_type else "html"

            if source_type == "pdf":
                extracted_text = extract_text_from_pdf_bytes(resp.content)
            else:
                soup = BeautifulSoup(resp.text, "html.parser")
                for tag in soup(["script", "style", "nav", "footer", "header"]):
                    tag.decompose()
                extracted_text = " ".join(soup.stripped_strings)

            content_hash = hashlib.sha256(resp.content).hexdigest()[:16]
            snippets = extract_evidence_snippets_from_text(extracted_text, mpn)

            evidence = SourcedEvidenceResult(
                brand=canonical_brand,
                mpn=mpn,
                domain=domain,
                source_url=str(resp.url),
                source_type=f"manufacturer_official_{source_type}",
                http_status=resp.status_code,
                content_hash=content_hash,
                extracted_text=extracted_text[:2000],
                evidence_snippets=snippets,
                provenance_score=1.0 if resp.status_code == 200 else 0.70,
                retrieved_at=timestamp,
            )

            SOURCED_DOCS_CACHE[cache_key] = evidence.to_dict()
            return evidence

    except Exception as e:
        logger.debug(f"Official manufacturer fetch error for {canonical_brand} {mpn}: {e}")
        evidence = SourcedEvidenceResult(
            brand=canonical_brand,
            mpn=mpn,
            domain=domain,
            source_url=target_url,
            source_type="distributor_feed",
            http_status=0,
            content_hash=hashlib.sha256(f"{canonical_brand}:{mpn}".encode()).hexdigest()[:16],
            extracted_text="",
            evidence_snippets={},
            provenance_score=0.70,
            retrieved_at=timestamp,
        )
        return evidence
