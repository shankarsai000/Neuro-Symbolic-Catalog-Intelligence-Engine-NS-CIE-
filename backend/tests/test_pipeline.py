from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.ai.schemas import EnrichmentRequest, ExtractedAttributes
from app.core.pipeline import run_enrichment_pipeline
from main import app

client = TestClient(app)


def test_extracted_attributes_schema():
    attrs = ExtractedAttributes(
        brand="FRIGIDAIRE®",
        item_type="Dishwasher",
        voltage="120 V",
        dimensions="50-1/4 in",
        material="Stainless Steel",
    )
    assert attrs.brand == "FRIGIDAIRE®"
    assert attrs.item_type == "Dishwasher"
    assert attrs.voltage == "120 V"
    assert attrs.dimensions == "50-1/4 in"


@pytest.mark.anyio
async def test_enrichment_pipeline_with_guardrails_and_agents():
    req = EnrichmentRequest(
        mfg_part_num="PDSH4816AF",
        part_desc="PDSH4816AF Dishwasher SS 120v 50.25in -- Unbranded --",
        raw_manuf="frigid air",
    )
    res = await run_enrichment_pipeline(req)

    assert res.mfg_part_num == "PDSH4816AF"
    assert res.attributes.brand == "FRIGIDAIRE®"
    assert res.attributes.item_type == "Dishwasher"
    assert res.attributes.voltage == "120 V"
    assert res.attributes.dimensions == "50-1/4 in"
    assert res.attributes.material in ("Stainless Steel", "SS", "SST")
    assert len(res.invoice_desc) <= 40
    assert res.invoice_desc == res.invoice_desc.upper()
    assert "-- Unbranded --" not in res.invoice_desc


def test_api_enrich_single_endpoint():
    payload = {
        "mfg_part_num": "PDSH4816AF",
        "part_desc": "PDSH4816AF Dishwasher SS 120v 50.25in -- Unbranded --",
        "raw_manuf": "frigid air",
    }
    response = client.post("/api/enrich-single", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["mfg_part_num"] == "PDSH4816AF"
    assert data["attributes"]["brand"] == "FRIGIDAIRE®"
    assert data["attributes"]["item_type"] == "Dishwasher"
    assert data["attributes"]["voltage"] == "120 V"
    assert data["attributes"]["dimensions"] == "50-1/4 in"
    assert "invoice_desc" in data
    assert len(data["invoice_desc"]) <= 40
    assert data["status"] in ("llm_extracted", "heuristic_fallback", "fallback_extracted")
    assert data["confidence_score"] > 0.0
