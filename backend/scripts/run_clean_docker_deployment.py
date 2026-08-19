from __future__ import annotations

import asyncio
import io
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
import pandas as pd
from fastapi.testclient import TestClient

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.benchmark.benchmark_engine import run_ground_truth_benchmark
from app.core.schema_validator import validate_252_column_dataframe
from app.db.database import init_db
from main import app

client = TestClient(app)


def check_docker_environment() -> dict[str, Any]:
    """Inspect local Docker installation and docker-compose availability."""
    info = {
        "docker_available": False,
        "docker_compose_available": False,
        "containers_running": 0,
        "services": {},
    }

    try:
        res = subprocess.run(["docker", "--version"], capture_output=True, text=True, check=False)
        if res.returncode == 0:
            info["docker_available"] = True
            info["docker_version"] = res.stdout.strip()
    except FileNotFoundError:
        info["docker_version"] = "Not found"

    try:
        res = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True, check=False)
        if res.returncode == 0:
            info["docker_compose_available"] = True
            info["docker_compose_version"] = res.stdout.strip()
    except FileNotFoundError:
        info["docker_compose_version"] = "Not found"

    # Try listing docker compose containers
    try:
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        res = subprocess.run(["docker", "compose", "ps", "--format", "json"], capture_output=True, text=True, cwd=root_dir, check=False)
        if res.returncode == 0 and res.stdout.strip():
            try:
                lines = [json.loads(line) for line in res.stdout.strip().split("\n") if line.strip()]
                info["containers_running"] = len(lines)
                for c in lines:
                    info["services"][c.get("Service", c.get("Name", "unknown"))] = c.get("State", "unknown")
            except Exception:
                pass
    except Exception:
        pass

    return info


async def run_clean_docker_deployment_verification() -> dict[str, Any]:
    """Execute complete Phase 19 clean-machine deployment verification."""
    start_time = time.time()
    print("=========================================================")
    print("NS-CIE PHASE 19: CLEAN-MACHINE DEPLOYMENT VERIFICATION")
    print("=========================================================")

    # Step 1: Inspect Docker environment
    print("[Step 1/6] Inspecting Docker environment and container stack configuration...")
    docker_info = check_docker_environment()
    print(f" -> Docker Available: {docker_info['docker_available']}")
    print(f" -> Docker Compose Available: {docker_info['docker_compose_available']}")
    print(f" -> Running Containers: {docker_info['containers_running']}")

    # Step 2: Validate docker-compose service definitions
    print("[Step 2/6] Validating docker-compose.yml container service definitions...")
    compose_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "docker-compose.yml"))
    assert os.path.exists(compose_path), "docker-compose.yml must exist at repository root"
    print(f" -> Found docker-compose.yml at: {compose_path}")

    expected_services = ["postgres", "redis", "backend", "worker", "frontend", "nginx"]
    with open(compose_path, "r", encoding="utf-8") as f:
        compose_content = f.read()

    for svc in expected_services:
        assert f"{svc}:" in compose_content, f"Missing service definition '{svc}' in docker-compose.yml"
    print(f" -> All 6 expected container services verified: {', '.join(expected_services)}")

    # Step 3: Validate Multi-Stage Frontend Dockerfile
    print("[Step 3/6] Validating multi-stage frontend Dockerfile...")
    frontend_df_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "Dockerfile"))
    assert os.path.exists(frontend_df_path)
    with open(frontend_df_path, "r", encoding="utf-8") as f:
        f_df_content = f.read()

    assert "AS builder" in f_df_content, "Frontend Dockerfile must use multi-stage build (builder stage)"
    assert "AS runner" in f_df_content, "Frontend Dockerfile must use multi-stage build (runner stage)"
    print(" -> Frontend Dockerfile multi-stage build confirmed.")

    # Step 4: Database & Engine Initialization
    print("[Step 4/6] Initializing production database and component health checks...")
    await init_db()

    health_resp = client.get("/api/system/health")
    assert health_resp.status_code == 200
    health_data = health_resp.json()
    print(f" -> Health Status: {health_data['status']}")
    print(f" -> Components: {health_data['components']}")

    metrics_resp = client.get("/api/system/metrics")
    assert metrics_resp.status_code == 200

    # Step 5: Execute Complete E2E Workflow
    print("[Step 5/6] Executing complete E2E workflow against production engine...")
    batch_create = client.post("/api/batches", json={"name": "Clean Deployment Phase 19 Batch"})
    assert batch_create.status_code == 200
    batch_id = batch_create.json()["batch_id"]

    input_csv_path = os.path.join(os.path.dirname(__file__), "..", "app", "data", "Unihack_ Sample Dataset - Input.csv")
    with open(input_csv_path, "rb") as f:
        csv_bytes = f.read()

    upload_resp = client.post(
        f"/api/batches/{batch_id}/upload",
        files={"file": ("clean_catalog.csv", io.BytesIO(csv_bytes), "text/csv")},
    )
    assert upload_resp.status_code == 200
    records_queued = upload_resp.json().get("total_records_queued", 0)
    print(f" -> Queued {records_queued} records for batch processing.")

    # Single enrichment check
    enrich_payload = {
        "mfg_part_num": "PDSH4816AF",
        "part_desc": "PDSH4816AF Dishwasher SS 120v 50.25in",
        "raw_manuf": "frigid air",
    }
    enrich_resp = client.post("/api/enrich-single", json=enrich_payload)
    assert enrich_resp.status_code == 200
    data = enrich_resp.json()
    assert data["attributes"]["brand"] == "FRIGIDAIRE®"

    # HITL Review check
    reviews_resp = client.get("/api/reviews")
    assert reviews_resp.status_code == 200

    # Export & 252-Column Schema validation
    export_resp = client.get("/api/export-sample")
    assert export_resp.status_code == 200
    exported_df = pd.read_csv(io.StringIO(export_resp.text), dtype=str)
    schema_report = validate_252_column_dataframe(exported_df)
    assert schema_report.is_valid is True
    print(f" -> 252-Column Schema Validation: Valid={schema_report.is_valid}")

    # Reload & Re-validate
    reload_df = pd.read_csv(io.StringIO(export_resp.text), dtype=str)
    reload_schema_report = validate_252_column_dataframe(reload_df)
    assert reload_schema_report.is_valid is True
    print(" -> Roundtrip Reload & Re-Validation PASSED (100% 252-column compliance).")

    # Benchmark run
    bench_report = await run_ground_truth_benchmark(
        run_name="Phase 19 Clean Deployment Benchmark",
        sample_limit=15,
    )
    print(f" -> Benchmark Exact Match Rate: {bench_report['metrics']['exact_match_accuracy'] * 100:.2f}%")
    print(f" -> Benchmark Schema Compliance: {bench_report['metrics']['schema_compliance'] * 100:.2f}%")

    # Step 6: Generate Final Deployment Report
    print("[Step 6/6] Generating clean deployment verification report...")
    execution_time = round(time.time() - start_time, 2)

    deployment_report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phase": "PHASE_19_CLEAN_MACHINE_DEPLOYMENT_VERIFICATION",
        "status": "PASSED",
        "docker_environment": docker_info,
        "services_verified": expected_services,
        "execution_time_seconds": execution_time,
        "records_queued": records_queued,
        "schema_compliance": True,
        "benchmark_metrics": bench_report["metrics"],
    }

    report_path = os.path.join(os.path.dirname(__file__), "..", "clean_deployment_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(deployment_report, f, indent=2)

    print("=========================================================")
    print(f"CLEAN DEPLOYMENT VERIFICATION PASSED IN {execution_time} SECONDS")
    print(f"Report Saved To: {os.path.abspath(report_path)}")
    print("=========================================================")
    return deployment_report


if __name__ == "__main__":
    asyncio.run(run_clean_docker_deployment_verification())
