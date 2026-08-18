from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.guardrails import (
    CatalogGuardrailEngine,
    decimal_to_fraction,
    enforce_uom_spacing,
    format_invoice_desc,
)
from app.core.sanitizer import clean_placeholders
from app.data.loader import master_data_loader
from main import app

client = TestClient(app)


def test_clean_placeholders():
    """Verify aggressive stripping of Unilog placeholders, supplier codes, and nulls."""
    raw = "PDSH4816AF Dishwasher SS 120v (2435) -- Unbranded -- [placeholder] N/A"
    cleaned = clean_placeholders(raw)
    assert "-- Unbranded --" not in cleaned
    assert "[placeholder]" not in cleaned
    assert "(2435)" not in cleaned
    assert "N/A" not in cleaned
    assert "PDSH4816AF Dishwasher SS 120v" in cleaned

    assert clean_placeholders("-- No Unilog Brand --") is None
    assert clean_placeholders("N/A") is None
    assert clean_placeholders("TBD") is None
    assert clean_placeholders(None) is None


def test_enforce_uom_spacing_and_casing():
    """Verify standard spacing and casing across electrical, dimensional, and packaging UOMs."""
    assert enforce_uom_spacing("24in") == "24 in"
    assert enforce_uom_spacing("120v") == "120 V"
    assert enforce_uom_spacing("15a") == "15 A"
    assert enforce_uom_spacing("60hz") == "60 Hz"
    assert enforce_uom_spacing("47db") == "47 dBA"
    assert enforce_uom_spacing("10pk") == "10 PK"
    assert enforce_uom_spacing("50lbs") == "50 lb"


def test_decimal_to_compound_fraction():
    """Verify conversion of decimal measurements into compound fraction standards."""
    assert decimal_to_fraction("50.25 in") == "50-1/4 in"
    assert decimal_to_fraction("24.125 in") == "24-1/8 in"
    assert decimal_to_fraction("0.5 in") == "1/2 in"
    assert decimal_to_fraction("7.75 in") == "7-3/4 in"
    assert decimal_to_fraction("24.25 x 35.5 in") == "24-1/4 x 35-1/2 in"


def test_invoice_description_compression_and_40_char_limit():
    """Verify invoice description compression rules:

    1. ALL CAPS
    2. <= 40 characters
    3. Progressive deterministic abbreviations (NO blind truncation)
    """
    long_desc = "FRIGIDAIRE STAINLESS STEEL BUILT-IN DISHWASHER 120 V 50.25 IN"
    compressed = format_invoice_desc(long_desc)

    assert len(compressed) <= 40
    assert compressed == compressed.upper()
    assert "SST" in compressed
    assert "BLTLN" in compressed
    assert "DISHWSHR" in compressed

    # Test extreme length compression
    extreme_desc = "MILWAUKEE INDUSTRIAL COMMERCIAL RECIPROCATING SAW BLADE 12 IN 10 PIECES WITH PREMIUM CASE FOR PROFESSIONAL USE"
    extreme_comp = format_invoice_desc(extreme_desc)
    assert len(extreme_comp) <= 40
    assert extreme_comp == extreme_comp.upper()
    # Ensure no trailing broken fragments
    assert not extreme_comp.endswith(" ")


def test_invoice_abbreviation_examples():
    """Verify specific required examples from mission prompt."""
    assert "SST" in format_invoice_desc("DISHWASHER STAINLESS STEEL 120V 24IN")
    assert "BLTLN" in format_invoice_desc("DISHWASHER BUILT-IN 120V 24IN")
    assert "PK" in format_invoice_desc("RECIPROCATING SAW BLADES PACKAGE 10 PIECES")


def test_numeric_sanity_validation():
    """Verify numeric physical boundaries check."""
    assert CatalogGuardrailEngine.validate_numeric_sanity("voltage", "120 V") is True
    assert CatalogGuardrailEngine.validate_numeric_sanity("voltage", "240 V") is True
    assert CatalogGuardrailEngine.validate_numeric_sanity("voltage", "50000 V") is False

    assert CatalogGuardrailEngine.validate_numeric_sanity("amperage", "15 A") is True
    assert CatalogGuardrailEngine.validate_numeric_sanity("amperage", "-10 A") is False

    assert CatalogGuardrailEngine.validate_numeric_sanity("dimensions", "24 in") is True
    assert CatalogGuardrailEngine.validate_numeric_sanity("dimensions", "5000 in") is False


def test_complex_unilog_transformations():
    """End-to-end transformation test combining all guardrails."""
    raw = "PDSH4816AF Dishwasher SS 120v 50.25in Built-In -- Unbranded -- (2435)"

    step1 = clean_placeholders(raw)
    assert "-- Unbranded --" not in step1
    assert "(2435)" not in step1

    step2 = enforce_uom_spacing(step1)
    assert "120 V" in step2
    assert "50.25 in" in step2

    step3 = decimal_to_fraction(step2)
    assert "50-1/4 in" in step3

    step4 = format_invoice_desc(step3)
    assert len(step4) <= 40
    assert step4 == step4.upper()
    assert "DISHWSHR" in step4


def test_api_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "engine" in data
    assert "nvidia_nim" in data


def test_api_test_guardrails_endpoint():
    payload = {"raw_text": "50.25in 120v Built-In -- Unbranded --"}
    response = client.post("/api/test-guardrails", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["cleaned_text"] == "50.25in 120v Built-In"
    assert data["uom_spaced_text"] == "50.25 in 120 V Built-In"
    assert data["fraction_converted_text"] == "50-1/4 in 120 V Built-In"
    assert len(data["invoice_desc_preview"]) <= 40
