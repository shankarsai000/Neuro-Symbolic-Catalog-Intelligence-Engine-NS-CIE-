from __future__ import annotations

import io
import pytest
from fastapi.testclient import TestClient

from app.db.database import init_db
from main import app

client = TestClient(app)


@pytest.mark.asyncio
async def test_full_e2e_batch_benchmark_and_export():
    await init_db()

    # 1. System Metrics check
    metrics_resp = client.get("/api/system/metrics")
    assert metrics_resp.status_code == 200
    assert metrics_resp.json()["status"] == "HEALTHY"

    # 2. Single Record Enrichment
    enrich_payload = {
        "mfg_part_num": "PDSH4816AF",
        "part_desc": "PDSH4816AF Dishwasher SS 120v 50.25in -- Unbranded --",
        "raw_manuf": "frigid air",
    }
    enrich_resp = client.post("/api/enrich-single", json=enrich_payload)
    assert enrich_resp.status_code == 200
    data = enrich_resp.json()
    assert data["attributes"]["brand"] == "FRIGIDAIRE®"
    assert data["attributes"]["item_type"] == "Dishwasher"
    assert data["attributes"]["voltage"] == "120 V"
    assert data["attributes"]["dimensions"] == "50-1/4 in"
    assert "DISHWASHER" in data["invoice_desc"]
    assert "120 V" in data["invoice_desc"]
    assert len(data["invoice_desc"]) <= 40
    assert "provenance" in data
    assert data["confidence_score"] > 0.0

    # 3. Batch Job Creation & CSV Upload
    batch_create = client.post("/api/batches", json={"name": "E2E Integration Test Batch"})
    assert batch_create.status_code == 200
    batch_id = batch_create.json()["batch_id"]

    csv_content = (
        "Mfg_Part_Num,Part_Desc,Part_Manuf\n"
        "PDSH4816AF,Dishwasher SS 120v 50.25in,Frigidaire\n"
        "49-94-0013,5in Metal Cut Off Disc,Milwaukee\n"
    )
    upload_resp = client.post(
        f"/api/batches/{batch_id}/upload",
        files={"file": ("test_feed.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")},
    )
    assert upload_resp.status_code == 200
    assert upload_resp.json()["total_records_queued"] == 2

    # 4. Run Ground-Truth Benchmark
    bench_resp = client.post(
        "/api/benchmark/run",
        json={"run_name": "E2E Automated Benchmark Run", "sample_limit": 10},
    )
    assert bench_resp.status_code == 200
    bench_data = bench_resp.json()
    assert bench_data["total_rows_evaluated"] == 10
    assert bench_data["exact_match_rate"] >= 0.0
    assert bench_data["schema_compliance_rate"] == 1.0

    # 5. Export 252-Column CSV Sample & Validate Schema
    export_resp = client.get("/api/export-sample")
    assert export_resp.status_code == 200
    assert "text/csv" in export_resp.headers.get("content-type", "")

    csv_exported = export_resp.text
    lines = csv_exported.strip().split("\n")
    headers = lines[0].split(",")
    assert len(headers) == 252
