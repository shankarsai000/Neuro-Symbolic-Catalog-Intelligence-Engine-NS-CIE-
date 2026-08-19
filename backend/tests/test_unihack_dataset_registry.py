"""Tests for dataset_registry module."""
from pathlib import Path
import pytest
from app.benchmark.dataset_registry import DatasetPaths, get_dataset_paths


def test_dataset_paths_defaults():
    paths = get_dataset_paths()
    assert paths.input_dataset.name == "Unihack_ Sample Dataset - Input.csv"
    assert paths.expected_output_dataset.name == "Unihack_ Expected Output - Delivery Format.csv"
    assert paths.input_dataset.exists(), f"Input dataset missing: {paths.input_dataset}"
    assert paths.expected_output_dataset.exists(), f"Golden dataset missing: {paths.expected_output_dataset}"


def test_dataset_paths_validate_success():
    paths = get_dataset_paths()
    errors = paths.validate()
    assert len(errors) == 0


def test_dataset_paths_missing_raises():
    fake_paths = DatasetPaths(
        input_dataset=Path("/non/existent/input.csv"),
        expected_output_dataset=Path("/non/existent/output.csv"),
    )
    errors = fake_paths.validate()
    assert len(errors) == 2
    with pytest.raises(FileNotFoundError):
        fake_paths.assert_valid()
