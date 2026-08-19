"""
Key Matcher — Determines join keys and matches input records to golden reference records.

Uses Mfg_Part_Num as the join key.
Records without ground truth are marked GROUND_TRUTH_UNAVAILABLE (NOT errors).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """Result of key matching between input and golden datasets."""
    input_key_column: str = "Mfg_Part_Num"
    golden_key_column: str = "Mfg_Part_Num"
    total_input_records: int = 0
    total_golden_records: int = 0
    matched_count: int = 0
    ground_truth_unavailable_count: int = 0
    golden_only_count: int = 0
    matched_mpns: list[str] = field(default_factory=list)
    unavailable_mpns: list[str] = field(default_factory=list)
    golden_only_mpns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_key_column": self.input_key_column,
            "golden_key_column": self.golden_key_column,
            "total_input_records": self.total_input_records,
            "total_golden_records": self.total_golden_records,
            "matched_count": self.matched_count,
            "ground_truth_unavailable_count": self.ground_truth_unavailable_count,
            "golden_only_count": self.golden_only_count,
            "matched_mpns": self.matched_mpns,
            "unavailable_mpns_sample": self.unavailable_mpns[:20],
            "golden_only_mpns": self.golden_only_mpns,
        }


def match_keys(
    input_df: pd.DataFrame,
    golden_df: pd.DataFrame,
    input_key: str = "Mfg_Part_Num",
    golden_key: str = "Mfg_Part_Num",
) -> MatchResult:
    """
    Match input dataset records to golden reference records by key.

    Uses exact uppercase-normalized matching on the specified key columns.
    """
    result = MatchResult(input_key_column=input_key, golden_key_column=golden_key)

    # Normalize keys
    input_keys = (
        input_df[input_key]
        .fillna("")
        .str.strip()
        .str.upper()
    )
    golden_keys = (
        golden_df[golden_key]
        .fillna("")
        .str.strip()
        .str.upper()
    )

    input_set = set(input_keys[input_keys != ""])
    golden_set = set(golden_keys[golden_keys != ""])

    result.total_input_records = len(input_set)
    result.total_golden_records = len(golden_set)

    matched = input_set & golden_set
    unavailable = input_set - golden_set
    golden_only = golden_set - input_set

    result.matched_count = len(matched)
    result.ground_truth_unavailable_count = len(unavailable)
    result.golden_only_count = len(golden_only)

    # Preserve original casing from golden dataset for matched MPNs
    golden_original = golden_df[golden_key].fillna("").str.strip()
    matched_original = [
        v for v in golden_original if v.upper() in matched
    ]
    result.matched_mpns = sorted(matched_original)
    result.unavailable_mpns = sorted(unavailable)
    result.golden_only_mpns = sorted(golden_only)

    logger.info(
        f"Key matching: {result.matched_count} matched, "
        f"{result.ground_truth_unavailable_count} without ground truth, "
        f"{result.golden_only_count} golden-only"
    )
    return result


def get_golden_record(
    golden_df: pd.DataFrame,
    mpn: str,
    key_column: str = "Mfg_Part_Num",
) -> pd.Series | None:
    """Retrieve a single golden record by MPN. Returns None if not found."""
    normalized = golden_df[key_column].fillna("").str.strip().str.upper()
    mask = normalized == mpn.strip().upper()
    if mask.any():
        return golden_df.loc[mask].iloc[0]
    return None
