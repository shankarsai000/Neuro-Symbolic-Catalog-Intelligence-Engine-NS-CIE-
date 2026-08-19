from __future__ import annotations

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.benchmark.benchmark_engine import (
    GroundTruthBenchmarkEngine,
    run_ground_truth_benchmark,
)
from app.db.database import async_session, init_db
from main import app

client = TestClient(app)


def test_ground_truth_loading():
    """Verify loading of official expected delivery CSV into ground-truth dictionary."""
    engine = GroundTruthBenchmarkEngine()
    gt_map = engine.load_ground_truth()

    assert len(gt_map) >= 2
    assert "PDSH4816AF" in gt_map
    assert "WDTS7024RZ" in gt_map

    pdsh = gt_map["PDSH4816AF"]
    assert "FRIGIDAIRE" in pdsh["BRAND_NAME"].upper()
    assert "DISHWASHER" in pdsh["INVOICE_DESC"]
    assert len(pdsh) == 252


@pytest.mark.asyncio
async def test_ground_truth_only_evaluation(tmp_path: Path):
    """Execute benchmark run strictly against ground-truth subset and verify computed metrics."""
    await init_db()
    engine = GroundTruthBenchmarkEngine(artifacts_dir=tmp_path)
    report = await engine.execute_run(
        run_name="Ground-Truth Pure Evaluation",
        ground_truth_only=True,
    )

    assert report["total_rows_evaluated"] == 2
    assert report["ground_truth_records_matched"] == 2
    metrics = report["metrics"]

    # Verify all 10 required metrics are mathematically computed and within bounds
    assert 0.0 <= metrics["exact_match_accuracy"] <= 1.0
    assert 0.0 <= metrics["field_level_accuracy"] <= 1.0
    assert 0.0 <= metrics["category_accuracy"] <= 1.0
    assert 0.0 <= metrics["brand_accuracy"] <= 1.0
    assert 0.0 <= metrics["mpn_accuracy"] <= 1.0
    assert 0.0 <= metrics["attribute_accuracy"] <= 1.0
    assert 0.0 <= metrics["invoice_description_compliance"] <= 1.0
    assert 0.0 <= metrics["uom_compliance"] <= 1.0
    assert 0.0 <= metrics["fraction_compliance"] <= 1.0
    assert metrics["schema_compliance"] == 1.0

    # Verify artifact generation
    assert (tmp_path / "predictions.csv").exists()
    assert (tmp_path / "errors.csv").exists()
    assert (tmp_path / "summary.json").exists()

    # Verify 252 columns in generated predictions.csv
    with open(tmp_path / "predictions.csv", "r", encoding="utf-8") as f:
        headers = f.readline().strip().split(",")
        assert len(headers) == 252


@pytest.mark.asyncio
async def test_error_reporting_completeness():
    """Verify that every error record includes all 7 required diagnostic fields."""
    await init_db()
    engine = GroundTruthBenchmarkEngine()
    report = await engine.execute_run(
        run_name="Diagnostic Error Verification Run",
        sample_limit=5,
    )

    errors = report.get("error_samples", [])
    for err in errors:
        assert "mpn" in err
        assert "field" in err
        assert "input" in err
        assert "expected" in err
        assert "actual" in err
        assert "confidence" in err
        assert "source" in err
        assert "reason" in err


@pytest.mark.asyncio
async def test_reproducibility_deterministic_hash():
    """Verify that running benchmark twice on identical input produces identical hash and metrics.

    Forces OFFLINE_HEURISTIC mode because live LLM outputs are inherently
    non-deterministic (temperature, server-side sampling) and would break
    hash reproducibility even with temperature=0.
    """
    await init_db()

    # Force deterministic (offline heuristic) mode for reproducibility
    from app.ai.nvidia_client import nvidia_client
    original_key = nvidia_client.api_key
    nvidia_client.api_key = "dummy_key_if_missing"

    try:
        report1 = await run_ground_truth_benchmark(
            run_name="Deterministic Run 1",
            sample_limit=5,
        )
        report2 = await run_ground_truth_benchmark(
            run_name="Deterministic Run 2",
            sample_limit=5,
        )

        assert report1["predictions_hash"] == report2["predictions_hash"]
        assert report1["metrics"] == report2["metrics"]
        assert report1["confidence_distribution"] == report2["confidence_distribution"]
    finally:
        nvidia_client.api_key = original_key


@pytest.mark.asyncio
async def test_custom_dataset_evaluation(tmp_path: Path):
    """Verify that benchmark computes scores on custom test dataset without hardcoding."""
    await init_db()
    custom_csv = tmp_path / "custom_input.csv"
    custom_csv.write_text(
        "Mfg_Part_Num,Part_Desc,Part_Manuf\n"
        "PDSH4816AF,Dishwasher SS 120v 50.25in,Frigidaire\n"
        "49-94-0013,5in Metal Cut Off Disc,Milwaukee\n"
        "DCB518ASTS06G,1/2x18 Sanding Belt,Diablo\n",
        encoding="utf-8",
    )

    engine = GroundTruthBenchmarkEngine(input_csv_path=custom_csv)
    report = await engine.execute_run(run_name="Custom Dataset Run")

    assert report["total_rows_evaluated"] == 3
    assert report["metrics"]["invoice_description_compliance"] == 1.0
    assert report["metrics"]["schema_compliance"] == 1.0


@pytest.mark.asyncio
async def test_benchmark_api_endpoints():
    """Verify end-to-end FastAPI benchmark execution, runs list, and error endpoints."""
    await init_db()
    # 1. Trigger benchmark run
    run_resp = client.post(
        "/api/benchmark/run",
        json={"run_name": "API Integration Benchmark", "sample_limit": 5, "ground_truth_only": False},
    )
    assert run_resp.status_code == 200
    data = run_resp.json()
    assert data["total_rows_evaluated"] == 5
    assert "metrics" in data
    assert "predictions_hash" in data

    run_id = data.get("run_id")
    if run_id:
        # 2. Get specific benchmark report
        get_resp = client.get(f"/api/benchmark/{run_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["run_name"] == "API Integration Benchmark"

        # 3. Get error details
        err_resp = client.get(f"/api/benchmark/{run_id}/errors")
        assert err_resp.status_code == 200
        assert "errors" in err_resp.json()

        # 4. Get per-record results
        res_resp = client.get(f"/api/benchmark/{run_id}/results")
        assert res_resp.status_code == 200
        assert "results" in res_resp.json()

    # 5. List benchmark runs
    runs_resp = client.get("/api/benchmark/runs")
    assert runs_resp.status_code == 200
    assert runs_resp.json()["total_runs"] >= 1
