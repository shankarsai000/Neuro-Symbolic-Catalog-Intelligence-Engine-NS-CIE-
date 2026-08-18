from __future__ import annotations

import pandas as pd
import pytest

from app.ai.schemas import EnrichmentRequest, ExtractedAttributes
from app.core.delivery import (
    DELIVERY_HEADERS,
    ExpectedSchema,
    build_channel_descriptions,
    generate_252_column_record,
)
from app.core.schema_validator import (
    DeliveryValidator,
    validate_252_column_dataframe,
)


def _generate_valid_test_record() -> dict:
    req = EnrichmentRequest(
        mfg_part_num="PDSH4816AF",
        part_desc="PDSH4816AF Dishwasher SS 120v 50.25in Built-In",
        raw_manuf="FRIGIDAIRE",
    )
    attrs = ExtractedAttributes(
        brand="FRIGIDAIRE®",
        item_type="Dishwasher",
        mpn="PDSH4816AF",
        voltage="120 V",
        dimensions="50-1/4 in",
        mounting="Built-In",
        material="Stainless Steel",
    )
    descs = build_channel_descriptions("FRIGIDAIRE®", "PDSH4816AF", attrs)
    return generate_252_column_record(req, "FRIGIDAIRE®", attrs, descs, 1.0)


def test_schema_validator_valid_record():
    """Verify a properly generated enriched record passes 100% semantic and structural validation."""
    record = _generate_valid_test_record()
    res = DeliveryValidator.validate_record(record)

    assert res.is_valid is True
    assert res.column_count_valid is True
    assert res.headers_valid is True
    assert res.order_valid is True
    assert len(res.issues) == 0
    assert "100% COMPLIANT" in res.summary


def test_schema_validator_missing_column():
    """Verify validator detects missing columns."""
    record = _generate_valid_test_record()
    # Remove one column
    del record["INVOICE_DESC"]

    res = DeliveryValidator.validate_record(record)
    assert res.is_valid is False
    assert res.column_count_valid is False
    assert "INVOICE_DESC" in res.missing_headers


def test_schema_validator_extra_unexpected_column():
    """Verify validator detects unexpected extra columns."""
    record = _generate_valid_test_record()
    record["UNEXPECTED_EXTRA_COLUMN"] = "Malicious or Invalid Extra"

    res = DeliveryValidator.validate_record(record)
    assert res.is_valid is False
    assert res.column_count_valid is False
    assert "UNEXPECTED_EXTRA_COLUMN" in res.unexpected_headers


def test_schema_validator_wrong_order():
    """Verify validator detects misordered columns even if total count is 252."""
    record = _generate_valid_test_record()
    keys = list(record.keys())
    # Swap first two keys
    keys[0], keys[1] = keys[1], keys[0]
    swapped_record = {k: record[k] for k in keys}

    res = DeliveryValidator.validate_record(swapped_record)
    assert res.is_valid is False
    assert res.order_valid is False
    assert len(res.misordered_headers) >= 1


def test_schema_validator_invalid_invoice_desc():
    """Verify validator flags invoice description length and casing violations."""
    record = _generate_valid_test_record()
    # Exceed 40 chars
    record["INVOICE_DESC"] = "THIS IS AN EXTREMELY LONG INVOICE DESCRIPTION THAT EXCEEDS 40 CHARS"
    res = DeliveryValidator.validate_record(record)
    assert res.is_valid is False
    assert any(i.issue_type == "LENGTH_EXCEEDED" for i in res.issues)

    # Test lowercase casing
    record["INVOICE_DESC"] = "lowercase invoice desc"
    res2 = DeliveryValidator.validate_record(record)
    assert res2.is_valid is False
    assert any(i.issue_type == "INVALID_CASING" for i in res2.issues)


def test_schema_validator_missing_required_data():
    """Verify validator flags empty required fields."""
    record = _generate_valid_test_record()
    record["PART_NUMBER"] = ""

    res = DeliveryValidator.validate_record(record)
    assert res.is_valid is False
    assert any(i.issue_type == "MISSING_REQUIRED" and i.column_name == "PART_NUMBER" for i in res.issues)


def test_schema_validator_invalid_glued_uom():
    """Verify validator flags glued UOM strings in attribute slots."""
    record = _generate_valid_test_record()
    record["ATTRIBUTE_VALUE 2"] = "120v"  # Glued UOM

    res = DeliveryValidator.validate_record(record)
    assert res.is_valid is False
    assert any(i.issue_type == "INVALID_UOM" for i in res.issues)


def test_delivery_validator_export_validated_csv():
    """Verify export_validated_csv produces valid CSV text and raises on invalid data."""
    valid_record = _generate_valid_test_record()
    csv_text = DeliveryValidator.export_validated_csv([valid_record])
    assert "PART_NUMBER" in csv_text
    assert "PDSH4816AF" in csv_text

    # Invalid record should raise ValueError
    invalid_record = dict(valid_record)
    invalid_record["INVOICE_DESC"] = "lowercase invalid"
    with pytest.raises(ValueError):
        DeliveryValidator.export_validated_csv([invalid_record])
