from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.ai.schemas import BatchEnrichmentRequest, EnrichmentRequest, ExtractedAttributes
from app.core.delivery import (
    DELIVERY_HEADERS,
    build_channel_descriptions,
    generate_252_column_record,
)
from main import app

client = TestClient(app)


def test_delivery_headers_count():
    assert len(DELIVERY_HEADERS) == 252
    assert "PART_NUMBER" in DELIVERY_HEADERS
    assert "INVOICE_DESC" in DELIVERY_HEADERS
    assert "MOBILE_DESC" in DELIVERY_HEADERS
    assert "Product Name" in DELIVERY_HEADERS
    assert "ATTRIBUTE_LABEL 1" in DELIVERY_HEADERS
    assert "Actual Image (Yes/No)" in DELIVERY_HEADERS


def test_build_channel_descriptions():
    attrs = ExtractedAttributes(
        brand="FRIGIDAIRE®",
        item_type="Dishwasher",
        voltage="120 V",
        dimensions="50-1/4 in",
        mounting="Leg",
        material="Stainless Steel",
    )
    descs = build_channel_descriptions(
        brand="FRIGIDAIRE®",
        mpn="PDSH4816AF",
        attrs=attrs,
    )

    assert len(descs["invoice_desc"]) <= 40
    assert descs["invoice_desc"] == descs["invoice_desc"].upper()
    assert 60 <= len(descs["mobile_desc"]) <= 80
    assert "FRIGIDAIRE®" in descs["product_title"]
    assert "120 V" in descs["long_desc"]


def test_generate_252_column_record():
    req = EnrichmentRequest(
        mfg_part_num="PDSH4816AF",
        part_desc="PDSH4816AF Dishwasher SS 120v 50.25in",
        raw_manuf="FRIGIDAIRE",
    )
    attrs = ExtractedAttributes(
        brand="FRIGIDAIRE®",
        item_type="Dishwasher",
        voltage="120 V",
        dimensions="50-1/4 in",
    )
    descs = build_channel_descriptions("FRIGIDAIRE®", "PDSH4816AF", attrs)
    record = generate_252_column_record(req, "FRIGIDAIRE®", attrs, descs)

    assert len(record) == 252
    assert record["PART_NUMBER"] == "PDSH4816AF"
    assert record["BRAND_NAME"] == "FRIGIDAIRE®"
    assert record["ATTRIBUTE_VALUE 1"] == "120"
    assert record["ATTRIBUTE_UOM 1"] == "V"
    assert record["Actual Image (Yes/No)"] == "Yes"


def test_api_enrich_batch_endpoint():
    payload = {
        "items": [
            {
                "mfg_part_num": "PDSH4816AF",
                "part_desc": "PDSH4816AF Dishwasher SS 120v 50.25in -- Unbranded --",
                "raw_manuf": "frigid air",
            },
            {
                "mfg_part_num": "49-94-0013",
                "part_desc": "49-94-0013 Milw 5\"x.045\"x7/8\" Metal Cut Off Disc -- No DIB Brand --",
                "raw_manuf": "Milwaukee Accessory (4031)",
            },
        ]
    }
    response = client.post("/api/enrich-batch", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["total_items"] == 2
    assert len(data["items"]) == 2
    assert data["average_confidence"] > 0.0
    assert data["items"][0]["canonical_brand"] == "FRIGIDAIRE®"
    assert data["items"][1]["canonical_brand"] == "MILWAUKEE®"


def test_api_export_sample_endpoint():
    response = client.get("/api/export-sample")
    assert response.status_code == 200
    assert "text/csv" in response.headers.get("content-type", "")
    assert "attachment" in response.headers.get("content-disposition", "")
    lines = response.text.strip().split("\n")
    assert len(lines) >= 2  # Header + rows
