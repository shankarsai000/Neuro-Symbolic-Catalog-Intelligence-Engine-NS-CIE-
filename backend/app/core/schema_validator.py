from __future__ import annotations

import csv
import io
import re
from typing import Any, Optional
import pandas as pd
from pydantic import BaseModel, Field

from app.core.delivery import DELIVERY_HEADERS, ExpectedSchema


class SchemaValidationIssue(BaseModel):
    row_number: int
    column_name: str
    issue_type: str  # MISSING_REQUIRED, LENGTH_EXCEEDED, INVALID_UOM, INVALID_CASING, UNEXPECTED_COLUMN, ORDER_MISMATCH, PLACEHOLDER_LEAK
    message: str
    actual_value: Optional[str] = None


class DeliveryValidationResult(BaseModel):
    is_valid: bool
    total_columns_found: int
    expected_column_count: int = 252
    column_count_valid: bool
    headers_valid: bool
    order_valid: bool
    missing_headers: list[str] = Field(default_factory=list)
    unexpected_headers: list[str] = Field(default_factory=list)
    misordered_headers: list[str] = Field(default_factory=list)
    total_rows_checked: int = 0
    valid_rows_count: int = 0
    invalid_rows_count: int = 0
    issues: list[SchemaValidationIssue] = Field(default_factory=list)
    summary: str = ""


# Backward-compatible alias
SchemaValidationReport = DeliveryValidationResult


class DeliveryValidator:
    """Comprehensive semantic and structural validator for the static 252-column Unilog delivery schema."""

    @staticmethod
    def validate_dataframe(df: pd.DataFrame) -> DeliveryValidationResult:
        issues: list[SchemaValidationIssue] = []
        columns_found = list(df.columns)
        col_count = len(columns_found)

        # 1. Exact Column Count Validation
        col_count_valid = (col_count == 252)

        # 2. Missing and Unexpected Header Validation
        missing_headers = [h for h in DELIVERY_HEADERS if h not in columns_found]
        unexpected_headers = [h for h in columns_found if h not in DELIVERY_HEADERS]
        headers_valid = (len(missing_headers) == 0 and len(unexpected_headers) == 0)

        # 3. Exact Column Ordering Validation
        misordered_headers: list[str] = []
        if col_count == 252 and headers_valid:
            for idx, (found, expected) in enumerate(zip(columns_found, DELIVERY_HEADERS)):
                if found != expected:
                    misordered_headers.append(f"Position {idx}: expected '{expected}', found '{found}'")
        order_valid = (len(misordered_headers) == 0)

        total_rows = len(df)
        valid_rows = 0
        invalid_rows = 0

        placeholder_leak_regex = re.compile(
            r"--\s*(?:Unbranded|No\s+Unilog\s+Brand|No\s+DIB\s+Brand)\s*--|\[placeholder\]",
            re.IGNORECASE,
        )
        glued_uom_regex = re.compile(r"\b\d+(\.\d+)?(in|v|a|w|hz|dba|lbs?|mm|cm)\b", re.IGNORECASE)

        # 4. Row-by-Row Semantic & Rule Validation
        for row_idx, row in df.iterrows():
            row_has_issue = False
            row_num = int(row_idx) + 1

            # Required Column Validation
            for req_col in ExpectedSchema.REQUIRED_COLUMNS:
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

            # INVOICE_DESC Validation (<= 40 chars & ALL CAPS)
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

            # Placeholder leak check across all cells
            for col in columns_found:
                cell_val = str(row[col]) if pd.notna(row[col]) else ""
                if cell_val and placeholder_leak_regex.search(cell_val):
                    issues.append(
                        SchemaValidationIssue(
                            row_number=row_num,
                            column_name=col,
                            issue_type="PLACEHOLDER_LEAK",
                            message=f"Uncleaned placeholder token detected in column '{col}'",
                            actual_value=cell_val,
                        )
                    )
                    row_has_issue = True

            # Glued UOM checks on ATTRIBUTE_VALUE 1..50
            for i in range(1, 51):
                val_col = f"ATTRIBUTE_VALUE {i}"
                if val_col in df.columns:
                    val_str = str(row[val_col]) if pd.notna(row[val_col]) else ""
                    if val_str and glued_uom_regex.search(val_str):
                        issues.append(
                            SchemaValidationIssue(
                                row_number=row_num,
                                column_name=val_col,
                                issue_type="INVALID_UOM",
                                message=f"Glued UOM detected in {val_col}: '{val_str}'",
                                actual_value=val_str,
                            )
                        )
                        row_has_issue = True

            if row_has_issue:
                invalid_rows += 1
            else:
                valid_rows += 1

        overall_valid = (
            col_count_valid
            and headers_valid
            and order_valid
            and (invalid_rows == 0)
        )

        summary_parts = []
        if col_count_valid and headers_valid and order_valid:
            summary_parts.append("252-Column Structural Schema: 100% COMPLIANT")
        else:
            summary_parts.append(f"252-Column Structural Schema: INVALID ({col_count}/252 columns)")

        summary_parts.append(f"Row Verification: {valid_rows}/{total_rows} rows valid")
        summary = " | ".join(summary_parts)

        return DeliveryValidationResult(
            is_valid=overall_valid,
            total_columns_found=col_count,
            expected_column_count=252,
            column_count_valid=col_count_valid,
            headers_valid=headers_valid,
            order_valid=order_valid,
            missing_headers=missing_headers,
            unexpected_headers=unexpected_headers,
            misordered_headers=misordered_headers[:10],
            total_rows_checked=total_rows,
            valid_rows_count=valid_rows,
            invalid_rows_count=invalid_rows,
            issues=issues[:50],
            summary=summary,
        )

    @staticmethod
    def validate_record(record: dict[str, Any]) -> DeliveryValidationResult:
        """Validate a single dictionary record against 252-column schema."""
        df = pd.DataFrame([record])
        return DeliveryValidator.validate_dataframe(df)

    @staticmethod
    def export_validated_csv(records: list[dict[str, Any]]) -> str:
        """Validate all records before exporting CSV-safe payload. Raises ValueError if invalid."""
        df = pd.DataFrame(records)
        val_report = DeliveryValidator.validate_dataframe(df)
        if not val_report.is_valid:
            raise ValueError(f"Delivery validation failed: {val_report.summary}. Issues: {len(val_report.issues)}")

        output = io.StringIO()
        df.reindex(columns=DELIVERY_HEADERS).to_csv(output, index=False, quoting=csv.QUOTE_MINIMAL)
        return output.getvalue()


# Top-level functional wrappers
def validate_252_column_dataframe(df: pd.DataFrame) -> DeliveryValidationResult:
    return DeliveryValidator.validate_dataframe(df)


def validate_252_column_csv_content(csv_text: str) -> DeliveryValidationResult:
    try:
        df = pd.read_csv(io.StringIO(csv_text), dtype=str)
        return DeliveryValidator.validate_dataframe(df)
    except Exception as e:
        return DeliveryValidationResult(
            is_valid=False,
            total_columns_found=0,
            column_count_valid=False,
            headers_valid=False,
            order_valid=False,
            summary=f"CSV Parsing Error: {str(e)}",
        )
