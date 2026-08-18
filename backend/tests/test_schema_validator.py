from __future__ import annotations

import pandas as pd
from app.core.delivery import DELIVERY_HEADERS
from app.core.schema_validator import (
    validate_252_column_csv_content,
    validate_252_column_dataframe,
)


def test_schema_validator_valid_dataframe():
    # Construct a perfectly compliant 252-column DataFrame
    row = {col: "" for col in DELIVERY_HEADERS}
    row["PART_NUMBER"] = "PDSH4816AF"
    row["Mfg_Part_Num"] = "PDSH4816AF"
    row["Part_Desc"] = "Dishwasher 120 V"
    row["MANUFACTURER_NAME"] = "FRIGIDAIRE®"
    row["BRAND_NAME"] = "FRIGIDAIRE®"
    row["MANUFACTURER_PART_NUMBER"] = "PDSH4816AF"
    row["INVOICE_DESC"] = "DISHWASHER LEG SST 120 V 50-1/4 IN"
    row["MOBILE_DESC"] = "FRIGIDAIRE®, Dishwasher, PDSH4816AF, Stainless Steel, 120 V"
    row["Product Name"] = "FRIGIDAIRE® PDSH4816AF Dishwasher"
    row["Actual Image (Yes/No)"] = "Yes"

    df = pd.DataFrame([row], columns=DELIVERY_HEADERS)
    report = validate_252_column_dataframe(df)

    assert report.is_valid is True
    assert report.total_columns_found == 252
    assert report.column_count_valid is True
    assert report.headers_valid is True
    assert report.order_valid is True
    assert report.invalid_rows_count == 0


def test_schema_validator_invalid_column_count():
    # DataFrame missing columns (e.g. only 5 columns)
    df = pd.DataFrame([{"PART_NUMBER": "123", "INVOICE_DESC": "ITEM"}])
    report = validate_252_column_dataframe(df)

    assert report.is_valid is False
    assert report.column_count_valid is False
    assert report.total_columns_found == 2
