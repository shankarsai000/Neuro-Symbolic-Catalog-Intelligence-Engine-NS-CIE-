"""
Unit tests for fixed-slot attribute alignment and schema preservation.
"""
import pytest
from app.ai.schemas import EnrichmentRequest, ExtractedAttributes
from app.core.delivery import AttributeSlotRegistry, SchemaMapper, generate_252_column_record


def test_missing_slot_does_not_shift_later_attributes():
    """Verify that an omitted attribute does not cause subsequent attributes to shift slot positions."""
    req = EnrichmentRequest(mfg_part_num="TEST-DW-1", part_desc="Dishwasher")
    attrs = ExtractedAttributes(
        brand="FRIGIDAIRE®",
        item_type="Dishwasher",
        mpn="TEST-DW-1",
        voltage="120 V",
        mounting="Leg",
        material="Stainless Steel",
        raw_specs={
            "spec_sections": {
                "Series": "Professional Series",
                "Model": "TEST-DW-1",
                "Number of Wash Cycles": "5",
                "Voltage Rating": "120 V",
                "Amperage Rating": "15 A",
                "Mounting Type": "Leg",
                # Plug Type is intentionally omitted!
                "Size": "24 in W x 24-1/4 in D",
                "Depth With Door Open": "50-1/4 in",
                "Minimum Height": "8-1/2 in Upper Rack",
                "Maximum Height": "10-3/8 in Upper Rack",
                "Sound Level": "47 dBA",
                "Material": "Stainless Steel",
            }
        },
    )

    descriptions = {"invoice_desc": "DISHWASHER LEG 5 SST 120V 15A", "long_desc": "Test"}
    record = SchemaMapper.map_to_252_column_record(req, "FRIGIDAIRE®", attrs, descriptions)

    # Slot 6: Mounting Type
    assert record["ATTRIBUTE_LABEL 6"] == "Mounting Type"
    assert record["ATTRIBUTE_VALUE 6"] == "Leg"

    # Slot 7: Plug Type (Must remain empty canonical slot, NOT shifted!)
    assert record["ATTRIBUTE_LABEL 7"] == "Plug Type"
    assert record["ATTRIBUTE_VALUE 7"] == ""
    assert record["ATTRIBUTE_UOM 7"] == ""

    # Slot 8: Size (Must stay in Slot 8, NOT shifted to Slot 7!)
    assert record["ATTRIBUTE_LABEL 8"] == "Size"
    assert record["ATTRIBUTE_VALUE 8"] == "24 in W x 24-1/4 in D"

    # Slot 9: Depth With Door Open (Must stay in Slot 9!)
    assert record["ATTRIBUTE_LABEL 9"] == "Depth With Door Open"
    assert record["ATTRIBUTE_VALUE 9"] == "50-1/4"
    assert record["ATTRIBUTE_UOM 9"] == "in"

    # Slot 12: Sound Level (Must stay in Slot 12!)
    assert record["ATTRIBUTE_LABEL 12"] == "Sound Level"
    assert record["ATTRIBUTE_VALUE 12"] == "47"
    assert record["ATTRIBUTE_UOM 12"] == "dBA"

    # Slot 13: Material (Must stay in Slot 13!)
    assert record["ATTRIBUTE_LABEL 13"] == "Material"
    assert record["ATTRIBUTE_VALUE 13"] == "Stainless Steel"


def test_canonical_alias_resolution():
    """Verify that different alias strings resolve to the correct canonical attribute slot."""
    req = EnrichmentRequest(mfg_part_num="TEST-FAUCET", part_desc="Faucet")
    attrs = ExtractedAttributes(
        brand="Moen",
        item_type="Kitchen Faucet",
        mpn="TEST-FAUCET",
        raw_specs={
            "spec_sections": {
                "flowrate": "1.5 GPM",  # alias for Flow Rate
                "mounting": "Deck Mount",  # alias for Mounting Type
                "connection": "3/8 in Compression",  # alias for Connection Type
                "color": "Chrome",  # alias for Finish
            }
        },
    )

    record = SchemaMapper.map_to_252_column_record(req, "Moen", attrs, {})

    # Slot 3: Flow Rate
    assert record["ATTRIBUTE_LABEL 3"] == "Flow Rate"
    assert record["ATTRIBUTE_VALUE 3"] == "1.5"
    assert record["ATTRIBUTE_UOM 3"] == "GPM"

    # Slot 4: Mounting Type
    assert record["ATTRIBUTE_LABEL 4"] == "Mounting Type"
    assert record["ATTRIBUTE_VALUE 4"] == "Deck Mount"

    # Slot 5: Connection Type
    assert record["ATTRIBUTE_LABEL 5"] == "Connection Type"
    assert record["ATTRIBUTE_VALUE 5"] == "3/8 in Compression"


def test_insertion_order_independence():
    """Verify that dictionary insertion order does not affect fixed slot placement."""
    spec_reversed = {
        "spec_sections": {
            "Material": "Stainless Steel",
            "Sound Level": "41 dBA",
            "Series": "Eco Series",
            "Voltage Rating": "120 V",
        }
    }

    req = EnrichmentRequest(mfg_part_num="TEST-ORDER", part_desc="Dishwasher")
    attrs = ExtractedAttributes(brand="Whirlpool®", item_type="Dishwasher", mpn="TEST-ORDER", raw_specs=spec_reversed)

    record = SchemaMapper.map_to_252_column_record(req, "Whirlpool®", attrs, {})

    assert record["ATTRIBUTE_LABEL 1"] == "Series"
    assert record["ATTRIBUTE_VALUE 1"] == "Eco Series"

    assert record["ATTRIBUTE_LABEL 4"] == "Voltage Rating"
    assert record["ATTRIBUTE_VALUE 4"] == "120"
    assert record["ATTRIBUTE_UOM 4"] == "V"

    assert record["ATTRIBUTE_LABEL 12"] == "Sound Level"
    assert record["ATTRIBUTE_VALUE 12"] == "41"
    assert record["ATTRIBUTE_UOM 12"] == "dBA"

    assert record["ATTRIBUTE_LABEL 13"] == "Material"
    assert record["ATTRIBUTE_VALUE 13"] == "Stainless Steel"


def test_extra_unmapped_attributes_overflow_to_later_slots():
    """Verify that extra unknown attributes are assigned to slots 16+ without corrupting fixed slots 1..15."""
    req = EnrichmentRequest(mfg_part_num="TEST-EXTRA", part_desc="Dishwasher")
    attrs = ExtractedAttributes(
        brand="Bosch",
        item_type="Dishwasher",
        mpn="TEST-EXTRA",
        raw_specs={
            "spec_sections": {
                "Series": "800 Series",
                "Custom Extra Spec": "Special Value",
            }
        },
    )

    record = SchemaMapper.map_to_252_column_record(req, "Bosch", attrs, {})

    # Slot 1: Series
    assert record["ATTRIBUTE_LABEL 1"] == "Series"
    assert record["ATTRIBUTE_VALUE 1"] == "800 Series"

    # Extra slot 16: Custom Extra Spec
    assert record["ATTRIBUTE_LABEL 16"] == "Custom Extra Spec"
    assert record["ATTRIBUTE_VALUE 16"] == "Special Value"
