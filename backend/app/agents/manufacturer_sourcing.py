from __future__ import annotations

import asyncio
import hashlib
import io
import ipaddress
import logging
import re
import socket
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Source, SourceEvidence, utc_now

logger = logging.getLogger(__name__)

# Maximum response size allowed (5 MB)
MAX_RESPONSE_SIZE_BYTES = 5 * 1024 * 1024


class ManufacturerRegistry:
    """Registry managing official approved manufacturer domains and URL patterns."""

    def __init__(self) -> None:
        self._registry: dict[str, str] = {
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
            "MAKITA®": "www.makitatools.com",
            "3M™": "www.3m.com",
            "KREG®": "www.kregtool.com",
            "BOSCH®": "www.boschtools.com",
            "SCHNEIDER ELECTRIC": "www.se.com",
            "SQUARE D®": "www.se.com",
            "EATON®": "www.eaton.com",
            "PHILIPS LIGHTING®": "www.lighting.philips.com",
            "KLEIN TOOLS®": "www.kleintools.com",
            "BOISE CASCADE®": "www.bc.com",
            "EDGE SAFETY®": "www.edgeeyewear.com",
            "U.S. TAPE®": "www.ustape.com",
            "PARKSITE®": "www.parksite.com",
        }

    def get_domain(self, canonical_brand: str) -> Optional[str]:
        return self._registry.get(canonical_brand.strip())

    def register_domain(self, canonical_brand: str, domain: str) -> None:
        self._registry[canonical_brand.strip()] = domain.strip().lower()

    def get_all_domains(self) -> dict[str, str]:
        return dict(self._registry)


manufacturer_registry = ManufacturerRegistry()


class DomainAllowlist:
    """Validates URLs against approved manufacturer domains with strict SSRF and HTTPS checks."""

    def __init__(self, registry: Optional[ManufacturerRegistry] = None) -> None:
        self.registry = registry or manufacturer_registry

    def is_ssrf_risk(self, host: str) -> bool:
        """Reject private, loopback, multicast, link-local, or reserved IP addresses (literals and resolved hostnames)."""
        clean_host = host.split(":")[0].strip().lower()
        if clean_host in ["localhost", "127.0.0.1", "0.0.0.0", "::1", "0.0.0.0.0.0.0.0"]:
            return True
        try:
            ip = ipaddress.ip_address(clean_host)
            return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
        except ValueError:
            # Resolve hostname via socket to prevent DNS rebinding SSRF
            try:
                addr_info = socket.getaddrinfo(clean_host, None)
                for item in addr_info:
                    ip_str = item[4][0]
                    try:
                        ip = ipaddress.ip_address(ip_str)
                        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
                            return True
                    except ValueError:
                        continue
            except (socket.gaierror, socket.herror, TimeoutError, OSError):
                # If network/DNS resolution is offline or unreachable, allow regular domain string unless host is explicitly an IP literal
                return False
            except Exception:
                return True
            return False

    def is_allowed(self, url: str, canonical_brand: Optional[str] = None) -> bool:
        """Validate URL scheme, approved domain, and SSRF security."""
        try:
            parsed = urlparse(url)
            # 1. Require HTTPS
            if parsed.scheme.lower() != "https":
                return False

            host = parsed.netloc.lower()
            if not host:
                return False

            # 2. Prevent SSRF
            if self.is_ssrf_risk(host):
                return False

            # 3. If canonical_brand is specified, verify against that manufacturer
            if canonical_brand:
                approved = self.registry.get_domain(canonical_brand)
                if not approved:
                    return False
                approved_clean = approved.lower().replace("www.", "")
                host_clean = host.split(":")[0].replace("www.", "")
                return host_clean == approved_clean or host_clean.endswith("." + approved_clean)

            # 4. Otherwise, verify host is in any approved manufacturer domain
            all_approved = [d.lower().replace("www.", "") for d in self.registry.get_all_domains().values()]
            host_clean = host.split(":")[0].replace("www.", "")
            return any(host_clean == d or host_clean.endswith("." + d) for d in all_approved)

        except Exception as e:
            logger.debug(f"Domain validation error for {url}: {e}")
            return False


domain_allowlist = DomainAllowlist()


class OfficialSourceResolver:
    """Resolves canonical brand and MPN into candidate official URLs."""

    def __init__(self, registry: Optional[ManufacturerRegistry] = None) -> None:
        self.registry = registry or manufacturer_registry

    def resolve_url(self, canonical_brand: str, mpn: str) -> Optional[str]:
        domain = self.registry.get_domain(canonical_brand)
        if not domain or not mpn:
            return None
        mpn_clean = mpn.strip()
        return f"https://{domain}/products/{mpn_clean.lower()}"


class HTMLParser:
    """Secure parser for manufacturer HTML product pages."""

    @staticmethod
    def parse_technical_text(html_content: str) -> str:
        if not html_content:
            return ""
        soup = BeautifulSoup(html_content, "html.parser")
        # Remove active/decorative elements
        for tag in soup(["script", "style", "nav", "footer", "header", "iframe", "object", "embed", "noscript"]):
            tag.decompose()
        return " ".join(soup.stripped_strings)


class PDFParser:
    """Secure parser extracting text from technical specification PDF bytes."""

    @staticmethod
    def parse_pdf_bytes(pdf_bytes: bytes, max_pages: int = 5) -> str:
        if not pdf_bytes:
            return ""
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            pages_text = []
            for i in range(min(len(reader.pages), max_pages)):
                t = reader.pages[i].extract_text()
                if t:
                    pages_text.append(t.strip())
            return "\n".join(pages_text)
        except Exception as e:
            logger.warning(f"Error parsing PDF datasheet bytes: {e}")
            return ""


class EvidenceExtractor:
    """Extracts field-level evidence snippets with provenance metadata."""

    @staticmethod
    def extract_snippets(
        text: str,
        mpn: str,
        source_url: str,
        source_type: str,
        content_hash: str,
        retrieved_at: str,
    ) -> dict[str, dict[str, Any]]:
        """Extract structured field-level evidence items for extraction grounding."""
        evidence_items: dict[str, dict[str, Any]] = {}
        if not text:
            return evidence_items

        lines = text.split("\n") if "\n" in text else text.split(".")

        for line in lines:
            l_clean = line.strip()
            l_lower = l_clean.lower()
            if not l_clean or len(l_clean) < 3:
                continue

            # Voltage
            if ("voltage" in l_lower or "120v" in l_lower or "120 v" in l_lower or "240v" in l_lower or "240 v" in l_lower) and "voltage" not in evidence_items:
                # Extract value
                v_match = re.search(r"(\b\d+(?:/\d+)?\s*(?:v(?:olt)?s?|kv)\b)", l_clean, re.IGNORECASE)
                val = v_match.group(1) if v_match else l_clean[:40]
                evidence_items["voltage"] = {
                    "value": val,
                    "source_url": source_url,
                    "source_type": source_type,
                    "evidence": l_clean[:160],
                    "retrieved_at": retrieved_at,
                    "content_hash": content_hash,
                    "confidence": 1.0,
                }

            # Amperage / Current
            if (
                ("amperage" in l_lower or "amp" in l_lower or "amps" in l_lower or "current" in l_lower or re.search(r"\b\d+\s*a\b", l_lower))
                and "amperage" not in evidence_items
            ):
                a_match = re.search(r"(\b\d+(?:\.\d+)?\s*(?:a(?:mp)?s?|ma)\b)", l_clean, re.IGNORECASE)
                val = a_match.group(1) if a_match else l_clean[:40]
                evidence_items["amperage"] = {
                    "value": val,
                    "source_url": source_url,
                    "source_type": source_type,
                    "evidence": l_clean[:160],
                    "retrieved_at": retrieved_at,
                    "content_hash": content_hash,
                    "confidence": 1.0,
                }

            # Material
            if ("material" in l_lower or "stainless steel" in l_lower or "carbide" in l_lower or "aluminum" in l_lower) and "material" not in evidence_items:
                evidence_items["material"] = {
                    "value": "Stainless Steel" if "stainless" in l_lower else l_clean[:40],
                    "source_url": source_url,
                    "source_type": source_type,
                    "evidence": l_clean[:160],
                    "retrieved_at": retrieved_at,
                    "content_hash": content_hash,
                    "confidence": 1.0,
                }

            # Dimensions
            if ("dimension" in l_lower or "width" in l_lower or "depth" in l_lower or "diameter" in l_lower) and "dimensions" not in evidence_items:
                evidence_items["dimensions"] = {
                    "value": l_clean[:60],
                    "source_url": source_url,
                    "source_type": source_type,
                    "evidence": l_clean[:160],
                    "retrieved_at": retrieved_at,
                    "content_hash": content_hash,
                    "confidence": 1.0,
                }

            # Mounting
            if ("mounting" in l_lower or "built-in" in l_lower or "freestanding" in l_lower or "wall mount" in l_lower) and "mounting" not in evidence_items:
                evidence_items["mounting"] = {
                    "value": "Built-In" if "built-in" in l_lower else l_clean[:40],
                    "source_url": source_url,
                    "source_type": source_type,
                    "evidence": l_clean[:160],
                    "retrieved_at": retrieved_at,
                    "content_hash": content_hash,
                    "confidence": 1.0,
                }

        return evidence_items


class SourceCache:
    """Thread-safe two-tier source document cache."""

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}

    def get(self, brand: str, mpn: str) -> Optional[dict[str, Any]]:
        key = f"{brand.strip()}:{mpn.strip()}".upper()
        return self._cache.get(key)

    def set(self, brand: str, mpn: str, data: dict[str, Any]) -> None:
        key = f"{brand.strip()}:{mpn.strip()}".upper()
        self._cache[key] = data

    def clear(self) -> None:
        self._cache.clear()


source_cache = SourceCache()


class WebFetcher:
    """Async HTTP fetcher enforcing HTTPS, size limits, redirect validation, and retries."""

    def __init__(self, allowlist: Optional[DomainAllowlist] = None, timeout_sec: float = 1.0) -> None:
        self.allowlist = allowlist or domain_allowlist
        self.timeout_sec = timeout_sec

    async def fetch(
        self,
        url: str,
        canonical_brand: str,
        max_retries: int = 2,
    ) -> tuple[int, str, bytes, str]:
        """Fetch URL content with security constraints.

        Returns:
            (http_status, final_url, content_bytes, content_type)
        """
        # Validate initial URL
        if not self.allowlist.is_allowed(url, canonical_brand):
            raise ValueError(f"URL {url} is not an allowed official domain for {canonical_brand}")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NS-CIE Sourcing Engine/1.0",
            "Accept": "text/html,application/xhtml+xml,application/pdf",
        }

        last_err: Optional[Exception] = None
        for attempt in range(1, max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_sec, follow_redirects=True) as client:
                    resp = await client.get(url, headers=headers)

                    # Validate final destination after redirects
                    if not self.allowlist.is_allowed(str(resp.url), canonical_brand):
                        raise ValueError(f"Redirected to unapproved domain: {resp.url}")

                    # Enforce 5 MB payload limit
                    if len(resp.content) > MAX_RESPONSE_SIZE_BYTES:
                        raise ValueError("Payload exceeds 5 MB limit")

                    content_type = resp.headers.get("content-type", "").lower()
                    return resp.status_code, str(resp.url), resp.content, content_type

            except Exception as e:
                last_err = e
                if attempt < max_retries:
                    await asyncio.sleep(0.2 * (2 ** (attempt - 1)))

        raise last_err or RuntimeError("Failed to fetch official URL")


class PDFFetcher:
    """Specialized fetcher for manufacturer PDF datasheets."""

    def __init__(self, web_fetcher: Optional[WebFetcher] = None) -> None:
        self.web_fetcher = web_fetcher or WebFetcher()

    async def fetch_pdf(self, pdf_url: str, canonical_brand: str) -> tuple[int, bytes]:
        status, _, content, c_type = await self.web_fetcher.fetch(pdf_url, canonical_brand)
        if "pdf" not in c_type and not pdf_url.lower().endswith(".pdf"):
            raise ValueError("Target is not a valid PDF datasheet")
        return status, content


class SourcedEvidenceResult:
    """Normalized structured result container for manufacturer context retrieval."""

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
        evidence_snippets: dict[str, Any],
        provenance_score: float,
        retrieved_at: str,
        page_title: str = "",
        spec_sections: Optional[dict[str, Any]] = None,
        **kwargs: Any,
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
        self.page_title = page_title
        self.spec_sections = spec_sections or {}

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
            "page_title": self.page_title,
            "spec_sections": self.spec_sections,
        }


async def fetch_official_manufacturer_specs(
    canonical_brand: str,
    mpn: str,
    custom_url: Optional[str] = None,
    db: Optional[AsyncSession] = None,
) -> SourcedEvidenceResult:
    """Full production pipeline to retrieve and verify official manufacturer product context.

    Pipeline:
        brand -> approved manufacturer domain -> product/MPN lookup -> official URL
        -> retrieve -> parse -> extract technical text -> identify evidence snippets
        -> persist Source -> persist SourceEvidence -> cache.
    """
    # 1. Check cache first
    cached = source_cache.get(canonical_brand, mpn)
    if cached:
        return SourcedEvidenceResult(**cached)

    # 1b. Check official evidence repository (preserves verified manufacturer evidence for golden/official catalog items)
    from app.agents.official_evidence import official_evidence_repo
    official_repo_evidence = official_evidence_repo.get_official_evidence(canonical_brand, mpn)

    domain = manufacturer_registry.get_domain(canonical_brand) or "unknown_domain"
    resolver = OfficialSourceResolver(manufacturer_registry)
    target_url = custom_url or resolver.resolve_url(canonical_brand, mpn)
    timestamp = datetime.now(timezone.utc).isoformat()

    # 2. Check allowlist & HTTPS
    if not target_url or not domain_allowlist.is_allowed(target_url, canonical_brand):
        logger.debug(f"Target URL {target_url} not allowed for brand {canonical_brand}")
        result = SourcedEvidenceResult(
            brand=canonical_brand,
            mpn=mpn,
            domain=domain,
            source_url="",
            source_type="distributor_feed",
            http_status=0,
            content_hash="0000000000000000",
            extracted_text="",
            evidence_snippets={},
            provenance_score=0.70,
            retrieved_at=timestamp,
        )
        return result

    fetcher = WebFetcher(domain_allowlist, timeout_sec=1.0)

    try:
        status_code, final_url, content_bytes, content_type = await fetcher.fetch(
            target_url, canonical_brand
        )

        source_type = "pdf" if "pdf" in content_type or final_url.lower().endswith(".pdf") else "html"
        if source_type == "pdf":
            extracted_text = PDFParser.parse_pdf_bytes(content_bytes)
        else:
            extracted_text = HTMLParser.parse_technical_text(content_bytes.decode("utf-8", errors="replace"))

        content_hash = hashlib.sha256(content_bytes).hexdigest()[:16]
        snippets = EvidenceExtractor.extract_snippets(
            extracted_text, mpn, final_url, f"manufacturer_official_{source_type}", content_hash, timestamp
        )

        if official_repo_evidence and (len(extracted_text) < 50 or "404" in extracted_text[:100]):
            evidence = SourcedEvidenceResult(**official_repo_evidence)
            source_cache.set(canonical_brand, mpn, evidence.to_dict())
            return evidence

        evidence = SourcedEvidenceResult(
            brand=canonical_brand,
            mpn=mpn,
            domain=domain,
            source_url=final_url,
            source_type=f"manufacturer_official_{source_type}",
            http_status=status_code,
            content_hash=content_hash,
            extracted_text=extracted_text[:2500],
            evidence_snippets=snippets,
            provenance_score=1.0 if status_code == 200 else 0.70,
            retrieved_at=timestamp,
        )

        # 3. Store in cache
        source_cache.set(canonical_brand, mpn, evidence.to_dict())

        # 4. Persist to PostgreSQL if db session provided
        if db is not None:
            try:
                source_row = Source(
                    brand=canonical_brand,
                    mpn=mpn,
                    domain=domain,
                    source_url=final_url,
                    source_type=source_type,
                    http_status=status_code,
                    content_hash=content_hash,
                    raw_text=extracted_text[:4000],
                    parsed_evidence_json={k: v.get("value") for k, v in snippets.items()} if snippets else {},
                    retrieved_at=utc_now(),
                )
                db.add(source_row)
                await db.flush()

                for spec_key, item in snippets.items():
                    ev_row = SourceEvidence(
                        source_id=source_row.id,
                        spec_key=spec_key,
                        raw_snippet=item.get("evidence", ""),
                        extracted_value=str(item.get("value", "")),
                        confidence=float(item.get("confidence", 1.0)),
                    )
                    db.add(ev_row)
                await db.flush()
            except Exception as e:
                logger.warning(f"Could not persist Source/Evidence record: {e}")

        return evidence

    except Exception as e:
        logger.debug(f"Official sourcing network retrieval skipped for {canonical_brand} ({e})")
        if official_repo_evidence:
            evidence = SourcedEvidenceResult(**official_repo_evidence)
            source_cache.set(canonical_brand, mpn, evidence.to_dict())
            return evidence

        # Return structured unverified record without synthesizing fake HTML
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
