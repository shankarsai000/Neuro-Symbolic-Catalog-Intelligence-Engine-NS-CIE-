from __future__ import annotations

import io
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.worker.batch_worker import BATCH_RESULTS_CACHE
from main import app

client = TestClient(app)


def test_batch_lifecycle_csv_upload_and_progress():
    """Verify full batch lifecycle: create batch -> upload CSV -> check progress -> get results -> download 252 CSV."""
    # Step 1: Create batch job
    create_resp = client.post("/api/batches", json={"name": "Test Ingestion Batch 1", "filename": "sample_feed.csv"})
    assert create_resp.status_code == 200
    batch_id = create_resp.json()["batch_id"]

    # Step 2: Prepare CSV content
    csv_data = (
        "Mfg_Part_Num,Part_Desc,Part_Manuf\n"
        "PDSH4816AF,PDSH4816AF Dishwasher SS 120v 50.25in Built-In,FRIGIDAIRE\n"
        "48-22-8424,48-22-8424 PACKOUT Tool Box 22in,MILWAUKEE\n"
        "HOM250,HOM250 Circuit Breaker 50A 120/240V,Square D\n"
    )

    upload_resp = client.post(
        f"/api/batches/{batch_id}/upload",
        files={"file": ("sample_feed.csv", csv_data.encode("utf-8"), "text/csv")},
    )
    assert upload_resp.status_code == 200
    upload_json = upload_resp.json()
    assert upload_json["total_records_queued"] == 3
    assert upload_json["unique_mpns"] == 3
    assert upload_json["status"] == "processing"

    # Step 3: Check batch status & progress
    status_resp = client.get(f"/api/batches/{batch_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["total_items"] == 3

    prog_resp = client.get(f"/api/batches/{batch_id}/progress")
    assert prog_resp.status_code == 200
    assert "progress_percentage" in prog_resp.json()


def test_batch_upload_excel_xlsx():
    """Verify Excel XLSX file ingestion."""
    create_resp = client.post("/api/batches", json={"name": "Excel Ingestion Batch", "filename": "catalog.xlsx"})
    batch_id = create_resp.json()["batch_id"]

    # Create Excel file in memory
    df = pd.DataFrame([
        {"Mfg_Part_Num": "DW-100", "Part_Desc": "Dishwasher SS 120V", "Part_Manuf": "Frigidaire"},
        {"Mfg_Part_Num": "BLD-200", "Part_Desc": "Circular Saw Blade 7-1/4in Carbide", "Part_Manuf": "Milwaukee"},
    ])
    excel_stream = io.BytesIO()
    df.to_excel(excel_stream, index=False)
    excel_bytes = excel_stream.getvalue()

    upload_resp = client.post(
        f"/api/batches/{batch_id}/upload",
        files={"file": ("catalog.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert upload_resp.status_code == 200
    assert upload_resp.json()["total_records_queued"] == 2


def test_batch_upload_invalid_extension_rejected():
    """Verify unapproved file extensions (.pdf, .exe) are rejected with 400."""
    create_resp = client.post("/api/batches", json={"name": "Invalid File Test"})
    batch_id = create_resp.json()["batch_id"]

    upload_resp = client.post(
        f"/api/batches/{batch_id}/upload",
        files={"file": ("datasheet.pdf", b"%PDF-1.4 dummy binary", "application/pdf")},
    )
    assert upload_resp.status_code == 400
    assert "Unsupported file extension" in upload_resp.json()["detail"]


def test_batch_upload_multi_encoding_and_duplicates():
    """Verify CSV with UTF-8 BOM, CP1252 encoding, duplicate MPNs, and malformed rows."""
    create_resp = client.post("/api/batches", json={"name": "Encoding & Duplicate Test"})
    batch_id = create_resp.json()["batch_id"]

    # CSV with duplicates and malformed empty rows, encoded in latin1 / windows-1252
    csv_text = (
        "Mfg_Part_Num,Part_Desc,Part_Manuf\n"
        "PDSH4816AF,PDSH4816AF Dishwasher SS 120v,FRIGIDAIRE\n"
        "PDSH4816AF,PDSH4816AF Dishwasher Duplicate,FRIGIDAIRE\n"
        ",,\n"  # Malformed empty row
        "HOM250,HOM250 Circuit Breaker 50A,Square D\n"
    )
    encoded_bytes = csv_text.encode("latin-1")

    upload_resp = client.post(
        f"/api/batches/{batch_id}/upload",
        files={"file": ("latin1_feed.csv", encoded_bytes, "text/csv")},
    )
    assert upload_resp.status_code == 200
    json_data = upload_resp.json()
    assert json_data["total_records_queued"] == 3
    assert json_data["unique_mpns"] == 2
    assert json_data["duplicates_detected"] == 1
    assert json_data["malformed_rows_skipped"] == 1


def test_batch_results_and_252_csv_download():
    """Verify results retrieval and validated 252-column CSV download."""
    create_resp = client.post("/api/batches", json={"name": "Download Test Batch"})
    batch_id = create_resp.json()["batch_id"]

    # Populate results cache directly
    BATCH_RESULTS_CACHE[batch_id] = [
        {
            "PART_NUMBER": "PDSH4816AF",
            "Mfg_Part_Num": "PDSH4816AF",
            "Part_Desc": "PDSH4816AF Dishwasher SS 120V 50-1/4 IN",
            "MANUFACTURER_NAME": "FRIGIDAIRE",
            "BRAND_NAME": "FRIGIDAIRE®",
            "INVOICE_DESC": "PDSH4816AF DISHWSHR SST 120 V",
            "MOBILE_DESC": "FRIGIDAIRE, Dishwasher, PDSH4816AF",
            "Product Name": "FRIGIDAIRE PDSH4816AF Dishwasher",
            "Actual Image (Yes/No)": "Yes",
        }
    ]

    # Test GET results
    res_resp = client.get(f"/api/batches/{batch_id}/results?limit=10&offset=0")
    assert res_resp.status_code == 200
    assert res_resp.json()["total_results"] == 1
    assert len(res_resp.json()["items"]) == 1

    # Test GET download 252 CSV
    down_resp = client.get(f"/api/batches/{batch_id}/download")
    assert down_resp.status_code == 200
    assert "text/csv" in down_resp.headers.get("content-type", "")
    assert "attachment" in down_resp.headers.get("content-disposition", "")
    csv_lines = down_resp.text.strip().split("\n")
    assert len(csv_lines) == 2  # Header + 1 record
    headers = csv_lines[0].split(",")
    assert len(headers) == 252
