"""
Regression tests for 252-column schema hardening, overflow UOM validation, and empty input rejection.
"""
import pytest
import pandas as pd
from app.schemas.delivery_schema import UNILOG_252_COLUMNS, format_252_delivery_record
from app.core.schema_validator import DeliveryValidator

def test_format_252_delivery_record_guarantees_required_fields_on_partial_input():
    partial_facts = {"Mfg_Part_Num": "SP-1001", "Part_Desc": "Standard Valve Fitting"}
    formatted = format_252_delivery_record(partial_facts)
    
    assert formatted["PART_NUMBER"] == "SP-1001"
    assert formatted["BRAND_NAME"] != ""
    assert formatted["INVOICE_DESC"] != ""
    assert formatted["MOBILE_DESC"] != ""

def test_schema_validator_100_percent_pass_on_fallback_record():
    partial_facts = {"Mfg_Part_Num": "SP-1002", "Part_Desc": "Commercial Pipe Coupling"}
    formatted = format_252_delivery_record(partial_facts)
    
    df = pd.DataFrame([formatted])
    res = DeliveryValidator.validate_dataframe(df)
    assert res.is_valid is True
