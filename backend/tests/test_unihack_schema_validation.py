"""Tests for 252-column schema validation integration."""
import pandas as pd
import pytest
from app.benchmark.dataset_registry import get_dataset_paths
from app.core.delivery import DELIVERY_HEADERS
from app.core.schema_validator import (
    validate_252_column_dataframe,
    validate_252_column_dataframe_detailed,
)


def test_validate_golden_dataset_schema():
    paths = get_dataset_paths()
    golden_df = pd.read_csv(paths.expected_output_dataset, dtype=str)
    result = validate_252_column_dataframe(golden_df)
    assert result.column_count_valid is True
    assert result.total_columns_found == 252
    assert result.headers_valid is True
    assert result.order_valid is True
    assert len(result.missing_headers) == 0


def test_validate_dataframe_detailed():
    record = {col: "" for col in DELIVERY_HEADERS}
    record["PART_NUMBER"] = "TEST-123"
    record["Mfg_Part_Num"] = "TEST-123"
    record["Part_Desc"] = "Test description"
    record["MANUFACTURER_NAME"] = "Test Brand"
    record["BRAND_NAME"] = "Test Brand"
    record["MANUFACTURER_PART_NUMBER"] = "TEST-123"
    record["INVOICE_DESC"] = "TEST INVOICE DESC"
    record["MOBILE_DESC"] = "Test Brand, Test Description, TEST-123 - Commercial Grade"
    record["Product Name"] = "Test Product"
    record["Actual Image (Yes/No)"] = "Yes"

    df = pd.DataFrame([record])
    res, res_df = validate_252_column_dataframe_detailed(df)
    assert res.is_valid is True
    assert len(res_df) == 1
    assert bool(res_df.iloc[0]["is_schema_valid"]) is True
    assert res_df.iloc[0]["issue_count"] == 0
