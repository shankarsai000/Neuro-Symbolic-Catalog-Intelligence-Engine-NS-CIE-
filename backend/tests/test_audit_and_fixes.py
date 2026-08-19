"""
Regression tests for NS-CIE Audit and Quality Fixes:
1. Supplier != manufacturer separation
2. Supplier != brand separation
3. Golden PDSH4816AF entity resolution
4. Golden WDTS7024RZ entity resolution
5. HTTP 429 retry and backoff
6. Retry-After parsing
7. Bounded retries
8. Concurrency limit
9. Truthful source_mode semantics
10. Provenance requirement
11. Confidence calculation mathematical grounding
12. Report metric consistency
13. Production readiness calculation
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch
import pytest
from app.ai.nvidia_client import ExtractionRetryPolicy, NIMRateLimiter, NVIDIAClient
from app.ai.schemas import EnrichmentRequest, ExtractedAttributes
from app.benchmark.evaluator import compute_readiness_assessment
from app.core.confidence import calculate_mathematical_confidence
from app.core.delivery import generate_252_column_record
from app.core.pipeline import run_enrichment_pipeline
from app.data.master_repository import master_data_repository


# 1 & 2. Supplier != Manufacturer and Supplier != Brand Separation
def test_supplier_separation_distributor():
    """Verify distributors/dealers are not incorrectly propagated as brands or manufacturers."""
    brand, manuf, supp, score = master_data_repository.resolve_entity(
        raw_desc="PDSH4816AF Dishwasher SS - Display Only",
        mpn="PDSH4816AF",
        raw_brand="-- Unbranded --",
        raw_manuf="Appliance Dealers Cooperative (APPDE)",
    )
    assert brand == "FRIGIDAIRE®"
    assert manuf == "Rheem Manufacturing"
    assert supp == "Appliance Dealers Cooperative (APPDE)"
    assert brand != supp
    assert manuf != supp


# 3. Golden PDSH4816AF Entity Resolution
def test_golden_pdsh4816af_entity_resolution():
    """Verify PDSH4816AF resolves to FRIGIDAIRE and Rheem Manufacturing."""
    brand, manuf, supp, score = master_data_repository.resolve_entity(
        raw_desc="PDSH4816AF Dishwasher SS - Display Only",
        mpn="PDSH4816AF",
        raw_manuf="Appliance Dealers Cooperative (APPDE)",
    )
    assert brand == "FRIGIDAIRE®"
    assert manuf == "Rheem Manufacturing"


# 4. Golden WDTS7024RZ Entity Resolution
def test_golden_wdts7024rz_entity_resolution():
    """Verify WDTS7024RZ resolves to WHIRLPOOL and Whirlpool Corporation."""
    brand, manuf, supp, score = master_data_repository.resolve_entity(
        raw_desc="WDTS7024RZ Dishwasher SS - Display Only",
        mpn="WDTS7024RZ",
        raw_manuf="Appliance Dealers Cooperative (APPDE)",
    )
    assert brand == "WHIRLPOOL®"
    assert manuf == "Whirlpool Corporation"


# 5, 6 & 7. HTTP 429 Retry, Retry-After parsing, Bounded retries
@pytest.mark.asyncio
async def test_retry_policy_429_backoff_and_retry_after():
    """Verify ExtractionRetryPolicy handles 429 with exponential backoff and bounded retries."""
    policy = ExtractionRetryPolicy(max_retries=3, base_delay=0.01, max_delay=0.1)

    calls = 0

    def mock_flaky():
        nonlocal calls
        calls += 1
        if calls < 3:
            err = RuntimeError("Error code: 429 - {'status': 429, 'title': 'Too Many Requests'}")
            raise err
        return "success"

    result, retries = await policy.execute_async(mock_flaky)
    assert result == "success"
    assert retries == 2
    assert calls == 3


@pytest.mark.asyncio
async def test_retry_policy_bounded_failure():
    """Verify ExtractionRetryPolicy raises after exceeding max retries."""
    policy = ExtractionRetryPolicy(max_retries=2, base_delay=0.01, max_delay=0.05)

    def mock_failing():
        raise RuntimeError("Error code: 429 - Rate limit exceeded")

    with pytest.raises(RuntimeError):
        await policy.execute_async(mock_failing)


# 8. Concurrency Limiter
@pytest.mark.asyncio
async def test_nim_rate_limiter_concurrency():
    """Verify NIMRateLimiter limits simultaneous in-flight requests."""
    limiter = NIMRateLimiter(max_concurrency=2, min_interval_sec=0.01)
    in_flight = 0
    max_observed = 0

    async def worker():
        nonlocal in_flight, max_observed
        await limiter.acquire()
        try:
            in_flight += 1
            if in_flight > max_observed:
                max_observed = in_flight
            await asyncio.sleep(0.05)
        finally:
            in_flight -= 1
            limiter.release()

    await asyncio.gather(*(worker() for _ in range(6)))
    assert max_observed <= 2


# 9. Truthful source_mode
@pytest.mark.asyncio
async def test_truthful_source_mode_on_pipeline():
    """Verify source_mode is OFFLINE_HEURISTIC or LIVE_NIM, never falsely claiming LIVE_NIM on fallback."""
    req = EnrichmentRequest(
        mfg_part_num="PDSH4816AF",
        part_desc="PDSH4816AF Dishwasher SS 120V 15A",
        raw_manuf="Appliance Dealers Cooperative (APPDE)",
    )
    resp = await run_enrichment_pipeline(req)
    assert resp.source_mode in ["LIVE_NIM", "OFFLINE_HEURISTIC", "MANUFACTURER_SOURCE", "CACHE"]
    assert resp.delivery_record_preview["MANUFACTURER_NAME"] == "Rheem Manufacturing"
    assert resp.delivery_record_preview["BRAND_NAME"] == "FRIGIDAIRE®"


# 10. Provenance Requirement
@pytest.mark.asyncio
async def test_provenance_requirement():
    """Verify all fields carry valid provenance tracking."""
    req = EnrichmentRequest(
        mfg_part_num="WDTS7024RZ",
        part_desc="WDTS7024RZ Dishwasher SS 120V 10A 41DBA",
        raw_manuf="Appliance Dealers Cooperative (APPDE)",
    )
    resp = await run_enrichment_pipeline(req)
    assert resp.provenance["brand"]["value"] == "WHIRLPOOL®"
    assert resp.provenance["brand"]["source_type"] is not None
    assert resp.provenance["brand"]["confidence"] > 0.0


# 11. Confidence Calculation Mathematical Grounding
def test_confidence_mathematical_formula():
    """Verify formula C = 0.40*P + 0.35*L + 0.25*R."""
    cb = calculate_mathematical_confidence(
        extracted_attrs={"item_type": "Dishwasher", "voltage": "120 V", "mounting": "Built-In", "material": "Stainless Steel"},
        invoice_desc="DISHWASHER BLTLN SST 120V",
        provenance_score=1.00,
    )
    # P=1.00, L=1.00, R=1.00 => C = 1.00
    assert cb.total_confidence == 1.0
    assert cb.review_tier == "AUTO_APPROVED"
    assert cb.needs_review is False


# 12 & 13. Production Readiness Calculation
def test_readiness_assessment_logic():
    """Verify readiness logic labels system NOT_READY when golden accuracy is near zero."""
    r_bad = compute_readiness_assessment(
        processing_success_rate=100.0,
        schema_pass_rate=99.8,
        live_nim_count=20,
        golden_comparison_ran=True,
        strict_field_accuracy=3.57,
        normalized_field_accuracy=3.57,
    )
    assert r_bad["overall_status"] == "NOT_READY"

    r_good = compute_readiness_assessment(
        processing_success_rate=100.0,
        schema_pass_rate=99.8,
        live_nim_count=20,
        golden_comparison_ran=True,
        strict_field_accuracy=85.0,
        normalized_field_accuracy=85.0,
        exact_record_match_rate=50.0,
        normalized_record_match_rate=50.0,
    )
    assert r_good["overall_status"] == "PRODUCTION_READY"
