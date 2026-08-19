"""Tests for key_matcher module."""
import pandas as pd
import pytest
from app.benchmark.dataset_registry import get_dataset_paths
from app.benchmark.key_matcher import match_keys, get_golden_record


def test_match_keys_real_datasets():
    paths = get_dataset_paths()
    input_df = pd.read_csv(paths.input_dataset, dtype=str)
    golden_df = pd.read_csv(paths.expected_output_dataset, dtype=str)

    result = match_keys(input_df, golden_df)
    assert result.total_input_records == 999  # 1000 rows with 1 duplicate MPN
    assert result.total_golden_records == 2
    assert result.matched_count == 2
    assert result.ground_truth_unavailable_count == 997
    assert result.golden_only_count == 0
    assert "PDSH4816AF" in result.matched_mpns
    assert "WDTS7024RZ" in result.matched_mpns


def test_get_golden_record():
    paths = get_dataset_paths()
    golden_df = pd.read_csv(paths.expected_output_dataset, dtype=str)

    rec = get_golden_record(golden_df, "PDSH4816AF")
    assert rec is not None
    assert rec["Mfg_Part_Num"] == "PDSH4816AF"
    assert rec["Product Name"] == "Dishwasher"

    missing = get_golden_record(golden_df, "NON_EXISTENT_MPN_999")
    assert missing is None
