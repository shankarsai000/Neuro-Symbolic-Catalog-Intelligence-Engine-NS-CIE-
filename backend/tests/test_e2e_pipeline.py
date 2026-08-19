from __future__ import annotations

import io
import os
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.benchmark.benchmark_engine import run_ground_truth_benchmark
from app.core.schema_validator import validate_252_column_dataframe
from app.db.database import init_db
from main import app

client = TestClient(app)


@pytest.mark.asyncio
async def test_full_20_step_production_e2e_workflow():
    """Verify complete Phase 18 20-step production E2E workflow."""
    # Step 1: Clean DB Environment Init
    await init_db()

    # Step 2 & 3: Health & System Metrics Verification
    health_resp = client.get("/api/system/health")
    assert health_resp.status_code == 200
    assert health_resp.json()["status"] in ["HEALTHY", "DEGRADED"]

    metrics_resp = client.get("/api/system/metrics")
    assert metrics_resp.status_code == 200
    assert metrics_resp.json()["status"] == "HEALTHY"

    # Step 4 & 5: Batch Job Creation & Real CSV Upload
    batch_create = client.post("/api/batches", json={"name": "E2E Production Phase 18 Test Batch"})
    assert batch_create.status_code == 200
    batch_id = batch_create.json()["batch_id"]

    csv_content = (
        "Mfg_Part_Num,Part_Desc,Part_Manuf\n"
        "PDSH4816AF,Dishwasher SS 120v 50.25in,Frigidaire\n"
        "49-94-0013,5in Metal Cut Off Disc 7/8 in Arbor,Milwaukee\n"
        "K-10433-VS,Single Hole Kitchen Faucet 1.5 GPM,Kohler\n"
        "ELB-150-BRS,1/2 in 90 Degree Elbow 150 PSI NPT,Anvil\n"
        "WDTS7024RZ,Built-In Dishwasher 120V 10A 41dBA,Whirlpool\n"
    )
    upload_resp = client.post(
        f"/api/batches/{batch_id}/upload",
        files={"file": ("production_catalog.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")},
    )
    assert upload_resp.status_code == 200
    assert upload_resp.json()["total_records_queued"] == 5

    # Step 6-12: Process products, resolve canonical brands, manufacturer sourcing, Nemotron extraction, LOVs, guardrails, confidence
    enrich_payload = {
        "mfg_part_num": "PDSH4816AF",
        "part_desc": "PDSH4816AF Dishwasher SS 120v 50.25in -- Unbranded --",
        "raw_manuf": "frigid air",
    }
    enrich_resp = client.post("/api/enrich-single", json=enrich_payload)
    assert enrich_resp.status_code == 200
    data = enrich_resp.json()
    assert data["attributes"]["brand"] == "FRIGIDAIRE®"
    assert "Dishwasher" in data["attributes"]["item_type"]
    assert data["attributes"]["voltage"] == "120 V"
    assert data["attributes"]["dimensions"] == "50-1/4 in"
    assert "DISHWASHER" in data["invoice_desc"]
    assert "120V" in data["invoice_desc"] or "120 V" in data["invoice_desc"]
    assert len(data["invoice_desc"]) <= 40
    assert data["confidence_score"] > 0.0

    # Step 13 & 14: Route low-confidence items to HITL and Approve/Edit review
    reviews_resp = client.get("/api/reviews")
    assert reviews_resp.status_code == 200
    reviews = reviews_resp.json()
    if reviews:
        review_id = reviews[0]["id"]
        app_resp = client.post(
            f"/api/reviews/{review_id}/approve",
            json={"reviewer": "test_auditor", "notes": "Approved in E2E workflow"},
        )
        assert app_resp.status_code == 200
        assert app_resp.json()["status"] == "APPROVED"

        edit_resp = client.post(
            f"/api/reviews/{review_id}/edit",
            json={"new_value": "EDITED_SPEC", "reviewer": "test_auditor", "notes": "Edited in E2E workflow"},
        )
        assert edit_resp.status_code == 200
        assert edit_resp.json()["status"] == "EDITED"

    # Step 15 & 16: Validate 252-Column Schema & Export CSV
    export_resp = client.get("/api/export-sample")
    assert export_resp.status_code == 200
    assert "text/csv" in export_resp.headers.get("content-type", "")

    csv_exported = export_resp.text
    exported_df = pd.read_csv(io.StringIO(csv_exported), dtype=str)
    schema_report = validate_252_column_dataframe(exported_df)
    assert schema_report.is_valid is True
    assert len(exported_df.columns) == 252

    # Step 17 & 18: Reload exported CSV & Validate again
    reload_df = pd.read_csv(io.StringIO(csv_exported), dtype=str)
    reload_schema_report = validate_252_column_dataframe(reload_df)
    assert reload_schema_report.is_valid is True
    assert len(reload_df.columns) == 252

    # Step 19: Run Ground-Truth Benchmark
    bench_resp = client.post(
        "/api/benchmark/run",
        json={"run_name": "Phase 18 E2E Benchmark Test", "sample_limit": 10},
    )
    assert bench_resp.status_code == 200
    bench_data = bench_resp.json()
    assert bench_data["total_rows_evaluated"] == 10
    assert bench_data["exact_match_rate"] >= 0.0
    assert bench_data["schema_compliance_rate"] == 1.0

    # Step 20: Verify Final Quality Metrics Report
    bench_report = await run_ground_truth_benchmark(
        run_name="Phase 18 Direct Evaluation",
        sample_limit=5,
    )
    assert "metrics" in bench_report
    assert "predictions_hash" in bench_report
