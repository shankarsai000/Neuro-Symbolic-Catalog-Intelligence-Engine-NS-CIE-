"""
Regression tests for 252-column schema hardening, overflow UOM validation, and empty input rejection.
"""
import pytest
import pandas as pd
from app.core.delivery import DELIVERY_HEADERS
from app.core.schema_validator import DeliveryValidator
from app.ai.schemas import EnrichmentRequest
from app.core.pipeline import run_enrichment_pipeline


def test_structured_glued_uom_detected_in_slot_1_to_15():
    """Verify that a glued UOM in structured slot 1..15 triggers an INVALID_UOM error."""
    record = {col: "" for col in DELIVERY_HEADERS}
    # Set required columns
    record["PART_NUMBER"] = "TEST-1"
    record["Mfg_Part_Num"] = "TEST-1"
    record["MANUFACTURER_PART_NUMBER"] = "TEST-1"
    record["BRAND_NAME"] = "TestBrand"
    record["MANUFACTURER_NAME"] = "TestManuf"
    record["INVOICE_DESC"] = "TEST PRODUCT DESC"
    record["MOBILE_DESC"] = "Test Product Mobile"
    record["Product Name"] = "Test Product"
    record["Actual Image (Yes/No)"] = "No"

    # Glued UOM in structured slot 1
    record["ATTRIBUTE_LABEL 1"] = "Voltage"
    record["ATTRIBUTE_VALUE 1"] = "120V"  # Glued UOM!

    df = pd.DataFrame([record])
    res = DeliveryValidator.validate_dataframe(df)

    uom_issues = [i for i in res.issues if i.issue_type == "INVALID_UOM"]
    assert len(uom_issues) == 1
    assert uom_issues[0].column_name == "ATTRIBUTE_VALUE 1"


def test_freeform_overflow_text_containing_embedded_uom_passes_schema():
    """Verify free-form multi-word text in overflow slots 16+ containing embedded units does NOT trigger INVALID_UOM."""
    record = {col: "" for col in DELIVERY_HEADERS}
    # Set required columns
    record["PART_NUMBER"] = "TEST-2"
    record["Mfg_Part_Num"] = "TEST-2"
    record["MANUFACTURER_PART_NUMBER"] = "TEST-2"
    record["BRAND_NAME"] = "3M"
    record["MANUFACTURER_NAME"] = "3M Company"
    record["INVOICE_DESC"] = "CUT OFF WHEEL ABRASIVE"
    record["MOBILE_DESC"] = "3M Cut Off Wheel Abrasive"
    record["Product Name"] = "Cut Off Wheel"
    record["Actual Image (Yes/No)"] = "No"

    # Multi-dimensional free-form text in overflow slot 16
    record["ATTRIBUTE_LABEL 16"] = "Wheel Size"
    record["ATTRIBUTE_VALUE 16"] = '12" x 1/8" x 20mm Metal Cut Off Wheel -T'

    df = pd.DataFrame([record])
    res = DeliveryValidator.validate_dataframe(df)

    uom_issues = [i for i in res.issues if i.issue_type == "INVALID_UOM"]
    assert len(uom_issues) == 0  # Should NOT fail as glued UOM!


def test_overflow_text_with_dimensions_and_fractions_passes_schema():
    """Verify overflow text with dimensions, fractions, and multi-units passes schema validation."""
    record = {col: "" for col in DELIVERY_HEADERS}
    record["PART_NUMBER"] = "TEST-3"
    record["Mfg_Part_Num"] = "TEST-3"
    record["MANUFACTURER_PART_NUMBER"] = "TEST-3"
    record["BRAND_NAME"] = "Milwaukee"
    record["MANUFACTURER_NAME"] = "Milwaukee Tool"
    record["INVOICE_DESC"] = "ABRASIVE WHEEL"
    record["MOBILE_DESC"] = "Milwaukee Abrasive Wheel"
    record["Product Name"] = "Abrasive Wheel"
    record["Actual Image (Yes/No)"] = "No"

    # Multi-unit overflow text in slot 18
    record["ATTRIBUTE_LABEL 18"] = "Spec Note"
    record["ATTRIBUTE_VALUE 18"] = '14" x 1/8" x 20mm Metal Cut Off Wheel'

    df = pd.DataFrame([record])
    res = DeliveryValidator.validate_dataframe(df)

    uom_issues = [i for i in res.issues if i.issue_type == "INVALID_UOM"]
    assert len(uom_issues) == 0


@pytest.mark.asyncio
async def test_empty_input_row_rejection():
    """Verify that an empty input request raises ValueError with EMPTY_INPUT_RECORD."""
    empty_req = EnrichmentRequest(mfg_part_num="", part_desc="")

    with pytest.raises(ValueError) as exc_info:
        await run_enrichment_pipeline(empty_req)

    assert "EMPTY_INPUT_RECORD" in str(exc_info.value)


def test_output_dataframe_structure_remains_252_columns():
    """Verify that output record structure always maintains exactly 252 columns."""
    record = {col: "test" for col in DELIVERY_HEADERS}
    df = pd.DataFrame([record])
    assert len(df.columns) == 252
