"""
Input Validator — Validates the real Unihack input dataset structure and content.

Generates:
  - input_validation_report.json
  - input_validation_errors.csv

Does NOT reject the entire dataset for individual malformed records.
Records errors per row.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import pandas as pd

from app.benchmark.dataset_registry import DatasetPaths

logger = logging.getLogger(__name__)

EXPECTED_INPUT_COLUMNS = [
    "Mfg_Part_Num",
    "Part_Desc",
    "E1_Brand",
    "Unilog_Brand",
    "DIB_Brand",
    "Part_Manuf",
]


@dataclass
class RowError:
    row_index: int
    mfg_part_num: str
    field: str
    error_type: str
    message: str


@dataclass
class InputValidationReport:
    path: str
    file_exists: bool = False
    readable: bool = False
    row_count: int = 0
    column_count: int = 0
    columns_found: list[str] = field(default_factory=list)
    expected_columns_present: list[str] = field(default_factory=list)
    missing_columns: list[str] = field(default_factory=list)
    unexpected_columns: list[str] = field(default_factory=list)
    duplicate_mpn_count: int = 0
    duplicate_mpns: list[str] = field(default_factory=list)
    missing_mpn_count: int = 0
    missing_part_desc_count: int = 0
    missing_manufacturer_count: int = 0
    row_errors: list[dict[str, Any]] = field(default_factory=list)
    is_valid: bool = False
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_input_dataset(paths: DatasetPaths) -> InputValidationReport:
    """Validate the real Unihack input dataset. Returns a report; never raises on data issues."""
    report = InputValidationReport(path=str(paths.input_dataset))
    errors: list[RowError] = []

    # File existence
    if not paths.input_dataset.exists():
        report.summary = f"Input dataset file not found: {paths.input_dataset}"
        return report
    report.file_exists = True

    # Read CSV
    try:
        df = pd.read_csv(paths.input_dataset, dtype=str)
    except Exception as e:
        report.summary = f"Failed to read input CSV: {e}"
        return report
    report.readable = True
    report.row_count = len(df)
    report.column_count = len(df.columns)
    report.columns_found = list(df.columns)

    # Column validation
    for col in EXPECTED_INPUT_COLUMNS:
        if col in df.columns:
            report.expected_columns_present.append(col)
        else:
            report.missing_columns.append(col)

    for col in df.columns:
        if col not in EXPECTED_INPUT_COLUMNS:
            report.unexpected_columns.append(col)

    # Key field validation
    if "Mfg_Part_Num" in df.columns:
        mpn_series = df["Mfg_Part_Num"].fillna("").str.strip()

        # Missing MPNs
        missing_mask = mpn_series == ""
        report.missing_mpn_count = int(missing_mask.sum())
        for idx in df.index[missing_mask]:
            errors.append(RowError(
                row_index=int(idx),
                mfg_part_num="",
                field="Mfg_Part_Num",
                error_type="MISSING_KEY",
                message="Mfg_Part_Num is empty or null",
            ))

        # Duplicate MPNs
        dup_mask = mpn_series.duplicated(keep=False) & (mpn_series != "")
        dup_values = mpn_series[dup_mask].unique().tolist()
        report.duplicate_mpn_count = len(dup_values)
        report.duplicate_mpns = dup_values
        for idx in df.index[mpn_series.duplicated(keep="first") & (mpn_series != "")]:
            errors.append(RowError(
                row_index=int(idx),
                mfg_part_num=mpn_series.iloc[idx],
                field="Mfg_Part_Num",
                error_type="DUPLICATE_KEY",
                message=f"Duplicate Mfg_Part_Num: {mpn_series.iloc[idx]}",
            ))

    # Part_Desc validation
    if "Part_Desc" in df.columns:
        desc_empty = df["Part_Desc"].fillna("").str.strip() == ""
        report.missing_part_desc_count = int(desc_empty.sum())
        for idx in df.index[desc_empty]:
            mpn = df["Mfg_Part_Num"].iloc[idx] if "Mfg_Part_Num" in df.columns else ""
            errors.append(RowError(
                row_index=int(idx),
                mfg_part_num=str(mpn) if pd.notna(mpn) else "",
                field="Part_Desc",
                error_type="MISSING_DESCRIPTION",
                message="Part_Desc is empty or null",
            ))

    # Manufacturer validation
    if "Part_Manuf" in df.columns:
        manuf_empty = df["Part_Manuf"].fillna("").str.strip() == ""
        report.missing_manufacturer_count = int(manuf_empty.sum())

    # Serialize errors
    report.row_errors = [asdict(e) for e in errors]
    report.is_valid = len(report.missing_columns) == 0 and report.missing_mpn_count == 0
    report.summary = (
        f"Input dataset: {report.row_count} rows, {report.column_count} columns. "
        f"Missing columns: {len(report.missing_columns)}. "
        f"Row errors: {len(errors)}. "
        f"Duplicate MPNs: {report.duplicate_mpn_count}."
    )
    return report


def save_input_validation_artifacts(
    report: InputValidationReport, output_dir: Path
) -> tuple[Path, Path]:
    """Save input_validation_report.json and input_validation_errors.csv."""
    output_dir.mkdir(parents=True, exist_ok=True)

    report_path = output_dir / "input_validation_report.json"
    report_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")

    errors_path = output_dir / "input_validation_errors.csv"
    if report.row_errors:
        pd.DataFrame(report.row_errors).to_csv(errors_path, index=False)
    else:
        errors_path.write_text("row_index,mfg_part_num,field,error_type,message\n", encoding="utf-8")

    return report_path, errors_path
