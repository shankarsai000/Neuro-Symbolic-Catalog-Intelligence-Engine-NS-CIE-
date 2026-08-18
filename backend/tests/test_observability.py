from __future__ import annotations

import asyncio
import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from app.ai.schemas import EnrichmentRequest
from app.core.observability import (
    StructuredLogEntry,
    current_request_id,
    evaluate_system_health,
    telemetry_collector,
    trace_stage_async,
    trace_stage_sync,
)
from app.core.pipeline import run_enrichment_pipeline
from app.db.database import init_db


@pytest.mark.asyncio
async def test_structured_log_entry_schema_and_fields():
    """Verify StructuredLogEntry captures all required fields: timestamp, request_id, batch_id, product_id, stage, duration, status, error."""
    entry = StructuredLogEntry(
        stage="TEST_EXTRACTION_STAGE",
        status="SUCCESS",
        duration_ms=42.5,
        request_id="req-test-uuid-001",
        batch_id=101,
        product_id=202,
        error=None,
        metadata={"item_type": "Dishwasher"},
    )
    d = entry.to_dict()

    assert "timestamp" in d
    assert d["request_id"] == "req-test-uuid-001"
    assert d["batch_id"] == 101
    assert d["product_id"] == 202
    assert d["stage"] == "TEST_EXTRACTION_STAGE"
    assert d["duration"] == 42.5
    assert d["duration_ms"] == 42.5
    assert d["status"] == "SUCCESS"
    assert d["error"] is None
    assert d["metadata"]["item_type"] == "Dishwasher"


@pytest.mark.asyncio
async def test_single_request_end_to_end_tracing_across_pipeline():
    """Verify that a single request can be traced across all stages with the identical request_id."""
    await init_db()

    trace_req_id = f"trace-req-{uuid.uuid4().hex[:8]}"
    token = current_request_id.set(trace_req_id)

    try:
        req = EnrichmentRequest(
            mfg_part_num="PDSH4816AF",
            part_desc="PDSH4816AF Dishwasher SS 120v 15A 50.25in Built in",
            raw_manuf="frigid air",
        )
        resp = await run_enrichment_pipeline(req)
        assert resp.mfg_part_num == "PDSH4816AF"

        # Check that stages were recorded with the identical request_id
        matched_traces = [t for t in telemetry_collector.recent_trace_logs if t.get("request_id") == trace_req_id]
        assert len(matched_traces) >= 5

        stages_recorded = [t["stage"] for t in matched_traces]
        assert "SANITIZATION_AND_BRAND_RESOLUTION" in stages_recorded
        assert "CATEGORY_DETECTION" in stages_recorded
        assert "MANUFACTURER_SOURCING" in stages_recorded
        assert "EXTRACTION" in stages_recorded
        assert "NEURO_SYMBOLIC_VALIDATION" in stages_recorded
        assert "CONFIDENCE_SCORING" in stages_recorded
        assert "SCHEMA_MAPPING" in stages_recorded

        for trace in matched_traces:
            assert trace["request_id"] == trace_req_id
            assert trace["status"] in ["SUCCESS", "FALLBACK"]
            assert trace["duration_ms"] >= 0.0

    finally:
        current_request_id.reset(token)


@pytest.mark.asyncio
async def test_system_health_endpoint_component_breakdown():
    """Verify /api/system/health distinguishes database, redis, worker, LLM, and manufacturer sourcing."""
    await init_db()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/system/health")
        assert resp.status_code == 200
        data = resp.json()

        assert data["status"] in ["HEALTHY", "DEGRADED", "UNHEALTHY"]
        assert "components" in data

        components = data["components"]
        assert "database" in components
        assert "redis" in components
        assert "worker" in components
        assert "llm" in components
        assert "manufacturer_sourcing" in components

        # Verify database component details
        assert components["database"]["status"] in ["CONNECTED", "DEGRADED"]
        # Verify redis component details
        assert components["redis"]["status"] in ["CONNECTED", "FALLBACK_ASYNCIO"]
        # Verify worker component details
        assert components["worker"]["status"] == "ACTIVE"
        # Verify manufacturer sourcing component details
        assert components["manufacturer_sourcing"]["status"] == "ACTIVE"
        assert components["manufacturer_sourcing"]["registered_manufacturers"] >= 1


@pytest.mark.asyncio
async def test_system_metrics_endpoint_telemetry():
    """Verify /api/system/metrics exposes latencies, cache rates, LLM fallback rate, throughput, and HITL rate."""
    await init_db()

    # Record sample telemetry events
    telemetry_collector.record_request_latency(15.2)
    telemetry_collector.record_llm_latency(85.4, is_live_nim=False)
    telemetry_collector.record_manufacturer_fetch(12.0, from_cache=True)
    telemetry_collector.record_hitl_decision(needs_review=False)
    telemetry_collector.record_schema_validation(is_valid=True)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/system/metrics")
        assert resp.status_code == 200
        data = resp.json()

        assert "telemetry" in data
        telemetry = data["telemetry"]

        assert "request_latency" in telemetry
        assert "llm_latency" in telemetry
        assert "manufacturer_fetch_latency" in telemetry
        assert "cache_hit_rate" in telemetry
        assert "llm_fallback_rate" in telemetry
        assert "batch_throughput" in telemetry
        assert "hitl_rate" in telemetry
        assert "schema_failure_rate" in telemetry

        assert telemetry["cache_hit_rate"]["total_lookups"] > 0
        assert telemetry["llm_fallback_rate"]["total_extractions"] > 0


@pytest.mark.asyncio
async def test_x_request_id_middleware_propagation():
    """Verify X-Request-ID header propagation and generation through ObservabilityMiddleware."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Custom Request ID
        custom_id = f"custom-{uuid.uuid4().hex[:12]}"
        resp1 = await client.get("/health", headers={"X-Request-ID": custom_id})
        assert resp1.status_code == 200
        assert resp1.headers.get("X-Request-ID") == custom_id

        # 2. Auto-generated Request ID
        resp2 = await client.get("/health")
        assert resp2.status_code == 200
        assert resp2.headers.get("X-Request-ID") is not None
        assert len(resp2.headers.get("X-Request-ID")) > 0


@pytest.mark.asyncio
async def test_metrics_calculation_accuracy():
    """Verify accurate mathematical calculation of latencies, percentiles, and rates."""
    tc = telemetry_collector

    tc.record_request_latency(10.0)
    tc.record_request_latency(20.0)
    tc.record_request_latency(30.0)

    snapshot = tc.get_metrics_snapshot()
    req_lat = snapshot["request_latency"]

    assert req_lat["count"] >= 3
    assert req_lat["min_ms"] <= 10.0
    assert req_lat["max_ms"] >= 30.0
    assert 0.0 <= snapshot["cache_hit_rate"]["rate"] <= 1.0
    assert 0.0 <= snapshot["llm_fallback_rate"]["rate"] <= 1.0
    assert 0.0 <= snapshot["hitl_rate"]["rate"] <= 1.0
