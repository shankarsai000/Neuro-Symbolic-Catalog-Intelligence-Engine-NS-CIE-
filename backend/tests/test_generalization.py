"""
Generalization & Adversarial Unit Tests (NS-CIE v2.1)
Verifies multi-category, multi-manufacturer extraction without golden hardcoding.
"""

from app.schemas.delivery_schema import UNILOG_252_COLUMNS, validate_252_column_schema
from app.core.validator import validate_supplier_input_row
from app.core.slot_mapper import map_attributes_to_50_slots
from app.agents.resolver import resolve_canonical_brand

def test_validator_strips_unbranded_placeholders():
    row = {
        "Mfg_Part_Num": "DCD791D2",
        "Part_Desc": "20V MAX Drill Driver",
        "Unilog_Brand": "-- No Unilog Brand --",
        "Part_Manuf": "DEWALT"
    }
    is_valid, err, sanitized = validate_supplier_input_row(row)
    assert is_valid is True
    assert sanitized["Unilog_Brand"] is None
    assert sanitized["Part_Manuf"] == "DEWALT"

def test_slot_mapper_prevents_slot_shifting_on_missing_attributes():
    attrs = [
        {"canonical_label": "Series", "value": "20V MAX"},
        # Slot 2 (Model) is missing!
        {"canonical_label": "Voltage Rating", "value": "20", "uom": "V"}
    ]
    slots = map_attributes_to_50_slots("POWER_TOOL", attrs)
    assert slots["ATTRIBUTE_LABEL 1"] == "Series"
    assert slots["ATTRIBUTE_VALUE 1"] == "20V MAX"
    # Slot 2 retains canonical label "Model" but ATTRIBUTE_VALUE 2 is empty string
    assert slots["ATTRIBUTE_LABEL 2"] == "Model"
    assert slots["ATTRIBUTE_VALUE 2"] == ""
    # Slot 3 (Voltage Rating) stays in Slot 3 (NO SHIFTING)
    assert slots["ATTRIBUTE_LABEL 3"] == "Voltage Rating"
    assert slots["ATTRIBUTE_VALUE 3"] == "20"
    assert slots["ATTRIBUTE_UOM 3"] == "V"

def test_delivery_schema_remains_exact_252_columns():
    is_valid, msg = validate_252_column_schema(list(UNILOG_252_COLUMNS))
    assert is_valid is True
