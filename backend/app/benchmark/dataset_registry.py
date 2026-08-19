"""
Dataset Registry — Central configuration for official Unihack dataset locations.

All dataset paths are resolved relative to the backend root directory.
The application fails clearly if expected datasets are missing.
No silent synthetic substitution is performed.
"""
from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass

# Backend root is two levels up from this file (app/benchmark/dataset_registry.py -> backend/)
_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent

# Default dataset directory
_DEFAULT_DATA_DIR = _BACKEND_ROOT / "app" / "data"


@dataclass(frozen=True)
class DatasetPaths:
    """Immutable container for official Unihack dataset file paths."""
    input_dataset: Path
    expected_output_dataset: Path

    def validate(self) -> list[str]:
        """Return list of validation errors. Empty list means all files exist."""
        errors: list[str] = []
        if not self.input_dataset.exists():
            errors.append(f"Input dataset not found: {self.input_dataset}")
        if not self.expected_output_dataset.exists():
            errors.append(f"Expected output dataset not found: {self.expected_output_dataset}")
        return errors

    def assert_valid(self) -> None:
        """Raise FileNotFoundError if any dataset file is missing."""
        errors = self.validate()
        if errors:
            raise FileNotFoundError(
                "Required Unihack dataset files are missing. "
                "Do NOT substitute synthetic datasets.\n" + "\n".join(errors)
            )


def _find_dataset_file(filename: str) -> Path:
    """Find a dataset file by checking standard directories in priority order."""
    candidate_dirs = [
        _BACKEND_ROOT / "data" / "2 datasets",
        _BACKEND_ROOT / "app" / "data" / "2 datasets",
        _BACKEND_ROOT / "app" / "data",
        _BACKEND_ROOT / "data",
    ]
    for cdir in candidate_dirs:
        candidate = cdir / filename
        if candidate.exists():
            return candidate
    return _BACKEND_ROOT / "data" / "2 datasets" / filename


def get_dataset_paths() -> DatasetPaths:
    """
    Resolve official Unihack dataset paths dynamically from environment or known locations.

    Environment variables:
        UNIHACK_INPUT_DATASET — path to the input CSV
        UNIHACK_EXPECTED_OUTPUT_DATASET — path to the expected delivery-format CSV
    """
    env_input = os.getenv("UNIHACK_INPUT_DATASET")
    input_path = Path(env_input) if env_input else _find_dataset_file("Unihack_ Sample Dataset - Input.csv")

    env_expected = os.getenv("UNIHACK_EXPECTED_OUTPUT_DATASET")
    expected_path = Path(env_expected) if env_expected else _find_dataset_file("Unihack_ Expected Output - Delivery Format.csv")

    return DatasetPaths(
        input_dataset=input_path,
        expected_output_dataset=expected_path,
    )


# Module-level singleton for convenient import
dataset_paths = get_dataset_paths()
