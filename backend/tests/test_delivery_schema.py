"""
Unit tests for 252-column Unilog Delivery Schema Contract.
"""

from app.schemas.delivery_schema import (
    UNILOG_252_COLUMNS,
    validate_252_column_schema,
    format_252_delivery_record,
)

def test_unilog_252_column_count_exact():
    assert len(UNILOG_252_COLUMNS) == 252

def test_validate_schema_success():
    is_valid, msg = validate_252_column_schema(list(UNILOG_252_COLUMNS))
    assert is_valid is True
    assert "compliant" in msg.lower()

def test_validate_schema_rejection_on_missing_column():
    incomplete = list(UNILOG_252_COLUMNS[:-1])
    is_valid, msg = validate_252_column_schema(incomplete)
    assert is_valid is False

def test_format_252_delivery_record_structure():
    sample_facts = {
        "Mfg_Part_Num": "DCD791D2",
        "MANUFACTURER_NAME": "DEWALT",
        "BRAND_NAME": "DEWALT",
        "ATTRIBUTE_LABEL 1": "Voltage",
        "ATTRIBUTE_VALUE 1": "20",
        "ATTRIBUTE_UOM 1": "V"
    }
    formatted = format_252_delivery_record(sample_facts)
    assert len(formatted) == 252
    assert formatted["Mfg_Part_Num"] == "DCD791D2"
    assert formatted["MANUFACTURER_NAME"] == "DEWALT"
    assert formatted["ATTRIBUTE_LABEL 1"] == "Voltage"
    assert formatted["ATTRIBUTE_LABEL 50"] == ""
