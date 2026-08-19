"""
Golden Validator — Validates the supplied Unihack expected-output delivery-format dataset.

The expected-output file is the authoritative golden reference.
It is NEVER modified or transformed to fit NS-CIE conventions.

Generates:
  - golden_validation_report.json
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import pandas as pd

from app.benchmark.dataset_registry import DatasetPaths
from app.core.delivery import DELIVERY_HEADERS as DELIVERY_COLUMNS

logger = logging.getLogger(__name__)


@dataclass
class GoldenValidationReport:
    path: str
    file_exists: bool = False
    readable: bool = False
    row_count: int = 0
    column_count: int = 0
    expected_column_count: int = 252
    columns_found: list[str] = field(default_factory=list)
    column_count_matches: bool = False
    column_names_match: bool = False
    column_order_matches: bool = False
    missing_columns: list[str] = field(default_factory=list)
    unexpected_columns: list[str] = field(default_factory=list)
    misplaced_columns: list[dict[str, Any]] = field(default_factory=list)
    duplicate_mpn_count: int = 0
    missing_mpn_count: int = 0
    golden_mpns: list[str] = field(default_factory=list)
    populated_fields_per_record: list[dict[str, int]] = field(default_factory=list)
    is_valid: bool = False
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_golden_dataset(paths: DatasetPaths) -> GoldenValidationReport:
    """Validate the Unihack expected-output delivery dataset. Never modifies the source."""
    report = GoldenValidationReport(path=str(paths.expected_output_dataset))

    if not paths.expected_output_dataset.exists():
        report.summary = f"Expected output dataset not found: {paths.expected_output_dataset}"
        return report
    report.file_exists = True

    try:
        df = pd.read_csv(paths.expected_output_dataset, dtype=str)
    except Exception as e:
        report.summary = f"Failed to read expected output CSV: {e}"
        return report
    report.readable = True
    report.row_count = len(df)
    report.column_count = len(df.columns)
    report.columns_found = list(df.columns)

    # Column count
    report.column_count_matches = report.column_count == report.expected_column_count

    # Column names
    expected_set = set(DELIVERY_COLUMNS)
    found_set = set(df.columns)
    report.missing_columns = sorted(expected_set - found_set)
    report.unexpected_columns = sorted(found_set - expected_set)
    report.column_names_match = len(report.missing_columns) == 0 and len(report.unexpected_columns) == 0

    # Column order
    if report.column_names_match and report.column_count_matches:
        report.column_order_matches = list(df.columns) == DELIVERY_COLUMNS
        if not report.column_order_matches:
            for i, (found, expected) in enumerate(zip(df.columns, DELIVERY_COLUMNS)):
                if found != expected:
                    report.misplaced_columns.append({
                        "index": i,
                        "expected": expected,
                        "found": found,
                    })
    else:
        report.column_order_matches = False

    # MPN key analysis
    mpn_col = None
    for candidate in ["Mfg_Part_Num", "MANUFACTURER_PART_NUMBER", "PART_NUMBER"]:
        if candidate in df.columns:
            mpn_col = candidate
            break

    if mpn_col:
        mpn_series = df[mpn_col].fillna("").str.strip()
        report.missing_mpn_count = int((mpn_series == "").sum())
        report.duplicate_mpn_count = int(mpn_series[mpn_series != ""].duplicated().sum())
        report.golden_mpns = mpn_series[mpn_series != ""].tolist()

    # Populated fields per record
    for row_idx, row in df.iterrows():
        populated = 0
        for col in df.columns:
            val = row[col]
            if pd.notna(val) and str(val).strip():
                populated += 1
        mpn = row.get("Mfg_Part_Num", row.get("MANUFACTURER_PART_NUMBER", f"row_{row_idx}"))
        report.populated_fields_per_record.append({
            "mfg_part_num": str(mpn) if pd.notna(mpn) else "",
            "populated_fields": populated,
            "total_fields": len(df.columns),
        })

    report.is_valid = report.file_exists and report.readable and report.column_count_matches
    report.summary = (
        f"Golden dataset: {report.row_count} rows, {report.column_count} columns. "
        f"Column count match: {report.column_count_matches}. "
        f"Column names match: {report.column_names_match}. "
        f"Golden MPNs: {report.golden_mpns}."
    )
    return report


def save_golden_validation_artifacts(
    report: GoldenValidationReport, output_dir: Path
) -> Path:
    """Save golden_validation_report.json."""
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "golden_validation_report.json"
    report_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return report_path
