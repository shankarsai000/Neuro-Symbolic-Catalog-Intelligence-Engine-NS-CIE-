from __future__ import annotations

import io
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.agents.manufacturer_sourcing import DomainAllowlist, WebFetcher, domain_allowlist
from app.core.config import settings
from app.core.security import (
    _RATE_LIMIT_STORE,
    RateLimitMiddleware,
    RequestSizeLimitMiddleware,
    validate_uploaded_file_security,
)
from main import app

client = TestClient(app)


def test_cors_origin_policy():
    """Verify CORS headers are returned for allowed origins."""
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") in ["http://localhost:3000", "*"]


def test_ssrf_protection_ip_literals():
    """Verify DomainAllowlist detects SSRF risks for loopback, private, and cloud metadata IPs."""
    allowlist = DomainAllowlist()

    # Loopback & local IPs
    assert allowlist.is_ssrf_risk("127.0.0.1") is True
    assert allowlist.is_ssrf_risk("localhost") is True
    assert allowlist.is_ssrf_risk("0.0.0.0") is True
    assert allowlist.is_ssrf_risk("::1") is True

    # Cloud metadata IP (AWS / GCP / Azure)
    assert allowlist.is_ssrf_risk("169.254.169.254") is True

    # Private RFC1918 ranges
    assert allowlist.is_ssrf_risk("10.0.0.1") is True
    assert allowlist.is_ssrf_risk("172.16.0.1") is True
    assert allowlist.is_ssrf_risk("192.168.1.1") is True


def test_ssrf_protection_domain_allowlist():
    """Verify arbitrary URL fetching is impossible and non-HTTPS is blocked."""
    # Arbitrary unapproved external URL -> rejected
    assert domain_allowlist.is_allowed("https://evil-attacker-site.com/steal-data") is False

    # HTTP non-HTTPS URL -> rejected
    assert domain_allowlist.is_allowed("http://www.frigidaire.com/products/pdsh4816af", "FRIGIDAIRE®") is False

    # SSRF IP literal URL -> rejected
    assert domain_allowlist.is_allowed("https://169.254.169.254/latest/meta-data/", "FRIGIDAIRE®") is False

    # Approved official HTTPS domain -> allowed
    assert domain_allowlist.is_allowed("https://www.frigidaire.com/products/pdsh4816af", "FRIGIDAIRE®") is True


@pytest.mark.asyncio
async def test_redirect_validation_blocks_ssrf():
    """Verify WebFetcher rejects unapproved domain initial URLs."""
    fetcher = WebFetcher()
    with pytest.raises(ValueError) as exc_info:
        await fetcher.fetch("https://unapproved-domain.com/data", canonical_brand="FRIGIDAIRE®")
    assert "not an allowed official domain" in str(exc_info.value)


def test_file_upload_validation_extension_checks():
    """Verify file upload validator blocks unauthorized file extensions."""
    disallowed_files = ["malicious.exe", "script.sh", "payload.py", "shell.php"]
    for fn in disallowed_files:
        with pytest.raises(HTTPException) as exc_info:
            validate_uploaded_file_security(fn, b"dummy content")
        assert exc_info.value.status_code == 400
        assert "Unsupported file extension" in exc_info.value.detail


def test_file_upload_validation_executable_binary_rejection():
    """Verify PE (Windows EXE) and ELF (Linux binary) executables are blocked by magic bytes."""
    # PE Header (MZ)
    with pytest.raises(HTTPException) as exc_info:
        validate_uploaded_file_security("catalog.csv", b"MZ\x90\x00\x03\x00\x00\x00")
    assert exc_info.value.status_code == 400
    assert "Executable binaries are prohibited" in exc_info.value.detail

    # ELF Header (\x7fELF)
    with pytest.raises(HTTPException) as exc_info:
        validate_uploaded_file_security("catalog.csv", b"\x7fELF\x01\x01\x01\x00")
    assert exc_info.value.status_code == 400
    assert "Executable binaries are prohibited" in exc_info.value.detail


def test_file_upload_validation_script_injection():
    """Verify CSV file containing embedded script tags or formula execution is rejected."""
    malicious_csv = b"Mfg_Part_Num,Part_Desc\nK-10433,<script>alert('xss')</script>"
    with pytest.raises(HTTPException) as exc_info:
        validate_uploaded_file_security("catalog.csv", malicious_csv)
    assert exc_info.value.status_code == 400
    assert "Potentially malicious script" in exc_info.value.detail


def test_file_upload_validation_invalid_xlsx():
    """Verify XLSX files without ZIP magic bytes (PK\x03\x04) are rejected."""
    with pytest.raises(HTTPException) as exc_info:
        validate_uploaded_file_security("catalog.xlsx", b"Not a valid zip file content")
    assert exc_info.value.status_code == 400
    assert "Missing ZIP magic header" in exc_info.value.detail


def test_request_payload_size_limit():
    """Verify oversized request content length header returns HTTP 413."""
    # Send content-length > 50 MB
    response = client.post(
        "/api/enrich-single",
        headers={"Content-Length": str(60 * 1024 * 1024)},
        json={"mfg_part_num": "TEST"},
    )
    assert response.status_code == 413
    assert response.json()["error"] == "Payload Too Large"


def test_rate_limit_middleware_enforcement():
    """Verify rate limiter blocks client exceeding request threshold with HTTP 429."""
    _RATE_LIMIT_STORE.clear()
    original_limit = settings.rate_limit_per_minute
    settings.rate_limit_per_minute = 5

    try:
        # First 5 requests succeed
        for _ in range(5):
            resp = client.get("/health")
            # /health bypasses rate limit, so let's call /api/test-guardrails or /api/system/metrics
            resp = client.post("/api/test-guardrails", json={"raw_text": "120v"})

        # 6th request should hit rate limit
        resp_blocked = client.post("/api/test-guardrails", json={"raw_text": "120v"})
        assert resp_blocked.status_code == 429
        assert resp_blocked.json()["error"] == "Too Many Requests"
        assert "Retry-After" in resp_blocked.headers
    finally:
        settings.rate_limit_per_minute = original_limit
        _RATE_LIMIT_STORE.clear()


def test_safe_exception_handler_suppresses_stack_traces():
    """Verify unhandled exception responses do not leak stack traces or internal secrets."""
    # Temporarily trigger unhandled exception endpoint or route
    response = client.get("/api/nonexistent-route-triggering-404")
    assert response.status_code in (404, 500)
    body = response.json()
    assert "traceback" not in body
    assert "stack" not in body
    assert "nvidia_api_key" not in str(body)
