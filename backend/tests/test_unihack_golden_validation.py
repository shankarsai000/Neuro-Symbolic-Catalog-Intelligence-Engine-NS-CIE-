"""Tests for golden_validator module."""
from pathlib import Path
import pytest
from app.benchmark.dataset_registry import DatasetPaths, get_dataset_paths
from app.benchmark.golden_validator import validate_golden_dataset, save_golden_validation_artifacts


def test_validate_real_golden_dataset():
    paths = get_dataset_paths()
    report = validate_golden_dataset(paths)
    assert report.file_exists is True
    assert report.readable is True
    assert report.row_count == 2
    assert report.column_count == 252
    assert report.column_count_matches is True
    assert report.column_names_match is True
    assert len(report.missing_columns) == 0
    assert len(report.golden_mpns) == 2
    assert "PDSH4816AF" in report.golden_mpns
    assert "WDTS7024RZ" in report.golden_mpns
    assert report.is_valid is True


def test_save_golden_validation_artifacts(tmp_path):
    paths = get_dataset_paths()
    report = validate_golden_dataset(paths)
    report_file = save_golden_validation_artifacts(report, tmp_path)
    assert report_file.exists()
    assert report_file.stat().st_size > 0


def test_missing_golden_dataset(tmp_path):
    fake_paths = DatasetPaths(
        input_dataset=tmp_path / "dummy.csv",
        expected_output_dataset=tmp_path / "non_existent.csv",
    )
    report = validate_golden_dataset(fake_paths)
    assert report.file_exists is False
    assert report.is_valid is False
