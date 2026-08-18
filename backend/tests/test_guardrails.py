from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.guardrails import (
    decimal_to_fraction,
    enforce_uom_spacing,
    format_invoice_desc,
)
from app.core.sanitizer import clean_placeholders
from app.data.loader import MasterDataLoader, master_data_loader
from main import app

client = TestClient(app)


def test_clean_placeholders():
    assert clean_placeholders("-- Unbranded --") is None
    assert clean_placeholders("  -- No Unilog Brand --  ") is None
    assert clean_placeholders("PDSH4816AF Dishwasher SS -- No DIB Brand --") == "PDSH4816AF Dishwasher SS"
    assert clean_placeholders("50.25in 120v -- Unbranded --") == "50.25in 120v"
    assert clean_placeholders(None) is None
    assert clean_placeholders("") is None
    assert clean_placeholders("nan") is None
    assert clean_placeholders("None") is None


def test_enforce_uom_spacing():
    assert enforce_uom_spacing("24in") == "24 in"
    assert enforce_uom_spacing("24inches") == "24 in"
    assert enforce_uom_spacing("120v") == "120 V"
    assert enforce_uom_spacing("15a") == "15 A"
    assert enforce_uom_spacing("47dba") == "47 dBA"
    assert enforce_uom_spacing("50.25in") == "50.25 in"
    assert enforce_uom_spacing("60hz") == "60 Hz"
    assert enforce_uom_spacing(None) == ""


def test_decimal_to_fraction():
    # Test standard fallback mappings
    assert decimal_to_fraction("50.25 in") == "50-1/4 in"
    assert decimal_to_fraction("0.5 in") == "1/2 in"
    assert decimal_to_fraction(".75 in") == "3/4 in"
    assert decimal_to_fraction("12.125 in") == "12-1/8 in"
    assert decimal_to_fraction("33.4375 in") == "33-7/16 in"

    # Custom fraction map support
    custom_map = {0.25: "1/4", 0.5: "1/2"}
    assert decimal_to_fraction("10.5 in", fraction_map=custom_map) == "10-1/2 in"
    assert decimal_to_fraction(None) == ""


def test_complex_unilog_transformations():
    raw = "33.4375in H x 23.875in W x 22.625in D 120v 10a 41dba -- No Unilog Brand --"
    sanitized = clean_placeholders(raw)
    assert sanitized == "33.4375in H x 23.875in W x 22.625in D 120v 10a 41dba"

    spaced = enforce_uom_spacing(sanitized)
    assert spaced == "33.4375 in H x 23.875 in W x 22.625 in D 120 V 10 A 41 dBA"

    fractional = decimal_to_fraction(spaced)
    assert fractional == "33-7/16 in H x 23-7/8 in W x 22-5/8 in D 120 V 10 A 41 dBA"


def test_format_invoice_desc():
    sample = "FRIGIDAIRE Dishwasher CleanBoost 120V 15A 50-1/4IN"
    result = format_invoice_desc(sample)
    assert len(result) <= 40
    assert result == "FRIGIDAIRE DISHWASHER CLEANBOOST 120V 15"
    assert format_invoice_desc("short desc") == "SHORT DESC"
    assert format_invoice_desc(None) == ""


def test_master_data_loader_fallback():
    loader = MasterDataLoader()
    fractions = loader.load_decimal_fractions()
    assert fractions[0.5] == "1/2"
    assert fractions[0.25] == "1/4"
    assert fractions[0.75] == "3/4"

    uoms = loader.load_uom_standards()
    assert uoms["in"] == "in"
    assert uoms["volt"] == "V"
    assert uoms["dba"] == "dBA"


def test_api_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "NS-CIE Backend Active"


def test_api_test_guardrails_endpoint():
    payload = {"raw_text": "50.25in 120v -- Unbranded --"}
    response = client.post("/api/test-guardrails", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["raw_text"] == "50.25in 120v -- Unbranded --"
    assert data["cleaned_text"] == "50.25in 120v"
    assert data["uom_spaced_text"] == "50.25 in 120 V"
    assert data["fraction_converted_text"] == "50-1/4 in 120 V"
    assert data["final_result"] == "50-1/4 in 120 V"
    assert data["invoice_desc_preview"] == "50-1/4 IN 120 V"
