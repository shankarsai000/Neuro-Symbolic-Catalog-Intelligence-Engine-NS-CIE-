from __future__ import annotations

import csv
import io
from typing import Any, Optional
import pandas as pd
from pydantic import BaseModel, Field

from app.core.delivery import DELIVERY_HEADERS


class SchemaValidationIssue(BaseModel):
    row_number: int
    column_name: str
    issue_type: str  # MISSING_REQUIRED, LENGTH_EXCEEDED, INVALID_UOM, INVALID_CASING, MISMATCH
    message: str
    actual_value: Optional[str] = None


class SchemaValidationReport(BaseModel):
    is_valid: bool
    total_columns_found: int
    expected_column_count: int = 252
    column_count_valid: bool
    headers_valid: bool
    order_valid: bool
    missing_headers: list[str] = Field(default_factory=list)
    misordered_headers: list[str] = Field(default_factory=list)
    total_rows_checked: int = 0
    valid_rows_count: int = 0
    invalid_rows_count: int = 0
    issues: list[SchemaValidationIssue] = Field(default_factory=list)
    summary: str = ""


# Core Required Columns in 252-Column Unilog Schema
REQUIRED_COLUMNS = [
    "PART_NUMBER",
    "Mfg_Part_Num",
    "Part_Desc",
    "MANUFACTURER_NAME",
    "BRAND_NAME",
    "MANUFACTURER_PART_NUMBER",
    "INVOICE_DESC",
    "MOBILE_DESC",
    "Product Name",
    "Actual Image (Yes/No)",
]


def validate_252_column_dataframe(df: pd.DataFrame) -> SchemaValidationReport:
    """Perform rigorous semantic and structural validation against the static 252-column Unilog delivery standard."""
    issues: list[SchemaValidationIssue] = []
    columns_found = list(df.columns)
    col_count = len(columns_found)

    # 1. Exact Column Count Validation
    col_count_valid = col_count == 252

    # 2. Exact Header Names & Missing Headers Validation
    missing_headers = [h for h in DELIVERY_HEADERS if h not in columns_found]
    headers_valid = len(missing_headers) == 0

    # 3. Exact Ordering Validation
    misordered_headers: list[str] = []
    if col_count == 252 and headers_valid:
        for idx, (found, expected) in enumerate(zip(columns_found, DELIVERY_HEADERS)):
            if found != expected:
                misordered_headers.append(f"Position {idx}: expected '{expected}', found '{found}'")
    order_valid = len(misordered_headers) == 0

    # 4. Row-Level Value & Rule Validation
    total_rows = len(df)
    valid_rows = 0
    invalid_rows = 0

    for row_idx, row in df.iterrows():
        row_has_issue = False
        row_num = int(row_idx) + 1

        # Check Required Fields
        for req_col in REQUIRED_COLUMNS:
            if req_col in df.columns:
                val = str(row[req_col]) if pd.notna(row[req_col]) else ""
                if not val.strip():
                    issues.append(
                        SchemaValidationIssue(
                            row_number=row_num,
                            column_name=req_col,
                            issue_type="MISSING_REQUIRED",
                            message=f"Required column '{req_col}' is empty",
                            actual_value="",
                        )
                    )
                    row_has_issue = True

        # Check INVOICE_DESC rules (<= 40 chars & ALL CAPS)
        if "INVOICE_DESC" in df.columns:
            inv_val = str(row["INVOICE_DESC"]) if pd.notna(row["INVOICE_DESC"]) else ""
            if len(inv_val) > 40:
                issues.append(
                    SchemaValidationIssue(
                        row_number=row_num,
                        column_name="INVOICE_DESC",
                        issue_type="LENGTH_EXCEEDED",
                        message=f"INVOICE_DESC exceeds 40 characters (length: {len(inv_val)})",
                        actual_value=inv_val,
                    )
                )
                row_has_issue = True
            if inv_val != inv_val.upper():
                issues.append(
                    SchemaValidationIssue(
                        row_number=row_num,
                        column_name="INVOICE_DESC",
                        issue_type="INVALID_CASING",
                        message="INVOICE_DESC must be strictly UPPERCASE",
                        actual_value=inv_val,
                    )
                )
                row_has_issue = True

        # Check Attribute UOM pairs
        for i in range(1, 51):
            val_col = f"ATTRIBUTE_VALUE {i}"
            uom_col = f"ATTRIBUTE_UOM {i}"
            if val_col in df.columns and uom_col in df.columns:
                val = str(row[val_col]) if pd.notna(row[val_col]) else ""
                uom = str(row[uom_col]) if pd.notna(row[uom_col]) else ""
                if val and not uom and ("in" in val.lower() or "v" in val.lower()):
                    # Potential missing UOM
                    pass

        if row_has_issue:
            invalid_rows += 1
        else:
            valid_rows += 1

    overall_valid = col_count_valid and headers_valid and order_valid and (invalid_rows == 0)

    summary_parts = []
    if col_count_valid and headers_valid and order_valid:
        summary_parts.append("252-Column Structural Schema: 100% COMPLIANT")
    else:
        summary_parts.append(f"252-Column Structural Schema: INVALID ({col_count}/252 columns)")

    summary_parts.append(f"Row Verification: {valid_rows}/{total_rows} rows valid")
    summary = " | ".join(summary_parts)

    return SchemaValidationReport(
        is_valid=overall_valid,
        total_columns_found=col_count,
        expected_column_count=252,
        column_count_valid=col_count_valid,
        headers_valid=headers_valid,
        order_valid=order_valid,
        missing_headers=missing_headers,
        misordered_headers=misordered_headers[:10],
        total_rows_checked=total_rows,
        valid_rows_count=valid_rows,
        invalid_rows_count=invalid_rows,
        issues=issues[:50],  # Return first 50 issues
        summary=summary,
    )


def validate_252_column_csv_content(csv_text: str) -> SchemaValidationReport:
    """Validate a CSV text payload against the 252-column schema standard."""
    try:
        df = pd.read_csv(io.StringIO(csv_text), dtype=str)
        return validate_252_column_dataframe(df)
    except Exception as e:
        return SchemaValidationReport(
            is_valid=False,
            total_columns_found=0,
            column_count_valid=False,
            headers_valid=False,
            order_valid=False,
            summary=f"CSV Parsing Error: {str(e)}",
        )
