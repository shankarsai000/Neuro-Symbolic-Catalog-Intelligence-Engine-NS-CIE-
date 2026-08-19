"""Tests for input_validator module."""
from pathlib import Path
import pandas as pd
import pytest
from app.benchmark.dataset_registry import DatasetPaths, get_dataset_paths
from app.benchmark.input_validator import validate_input_dataset, save_input_validation_artifacts


def test_validate_real_input_dataset():
    paths = get_dataset_paths()
    report = validate_input_dataset(paths)
    assert report.file_exists is True
    assert report.readable is True
    assert report.row_count == 1000
    assert report.column_count == 6
    assert "Mfg_Part_Num" in report.expected_columns_present
    assert "Part_Desc" in report.expected_columns_present
    assert len(report.missing_columns) == 0


def test_save_input_validation_artifacts(tmp_path):
    paths = get_dataset_paths()
    report = validate_input_dataset(paths)
    report_file, errors_file = save_input_validation_artifacts(report, tmp_path)
    assert report_file.exists()
    assert errors_file.exists()
    assert report_file.stat().st_size > 0


def test_missing_input_dataset(tmp_path):
    fake_paths = DatasetPaths(
        input_dataset=tmp_path / "non_existent.csv",
        expected_output_dataset=tmp_path / "dummy.csv",
    )
    report = validate_input_dataset(fake_paths)
    assert report.file_exists is False
    assert report.is_valid is False
