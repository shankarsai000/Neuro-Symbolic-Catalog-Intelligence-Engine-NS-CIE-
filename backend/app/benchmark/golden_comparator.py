"""
Golden Comparator — Compares NS-CIE output against the supplied expected-output dataset.

ONLY compares records that have ground truth.
Per-field classification: EXACT_MATCH, NORMALIZED_MATCH, MISMATCH, EXPECTED_EMPTY, GROUND_TRUTH_UNAVAILABLE.
Records normalization rules for every NORMALIZED_MATCH.
Does NOT silently normalize differences.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# Fields to compare when present in golden reference
COMPARISON_FIELDS = [
    "BRAND_NAME", "MANUFACTURER_NAME", "MANUFACTURER_PART_NUMBER",
    "MOBILE_DESC", "INVOICE_DESC", "SHORT_DESC", "LONG_DESC1",
    "RETAIL_DESC", "MARKETING_DESCRIPTION",
    "Classpath", "Dept", "Class", "Fine",
    "MFR URL", "Product Name", "With", "Standard/Approvals",
    "Warranty", "Country Of Origin", "Discontinued",
    "Selling Qty", "Selling UOM",
    "Product Image", "Specification Sheet",
    "Actual Image (Yes/No)",
]

# Add ITEM_FEATURES 1-20
COMPARISON_FIELDS += [f"ITEM_FEATURES_{i}" for i in range(1, 21)]

# Add ATTRIBUTE_LABEL/VALUE/UOM 1-50
for i in range(1, 51):
    COMPARISON_FIELDS.append(f"ATTRIBUTE_LABEL {i}")
    COMPARISON_FIELDS.append(f"ATTRIBUTE_VALUE {i}")
    COMPARISON_FIELDS.append(f"ATTRIBUTE_UOM {i}")

# Add identifiers
COMPARISON_FIELDS += ["UPC", "EAN", "GTIN", "UNSPSC"]


@dataclass
class FieldComparison:
    field_name: str
    expected_value: str
    actual_value: str
    comparison_type: str  # EXACT_MATCH, NORMALIZED_MATCH, MISMATCH, EXPECTED_EMPTY
    normalization_rule: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "expected_value": self.expected_value,
            "actual_value": self.actual_value,
            "comparison_type": self.comparison_type,
            "normalization_rule": self.normalization_rule,
        }


@dataclass
class RecordComparison:
    mfg_part_num: str
    total_compared_fields: int = 0
    exact_matches: int = 0
    normalized_matches: int = 0
    mismatches: int = 0
    expected_empty: int = 0
    field_comparisons: list[FieldComparison] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        denom = self.exact_matches + self.normalized_matches + self.mismatches
        if denom == 0:
            return 0.0
        return (self.exact_matches + self.normalized_matches) / denom

    def to_dict(self) -> dict[str, Any]:
        return {
            "mfg_part_num": self.mfg_part_num,
            "total_compared_fields": self.total_compared_fields,
            "exact_matches": self.exact_matches,
            "normalized_matches": self.normalized_matches,
            "mismatches": self.mismatches,
            "expected_empty": self.expected_empty,
            "accuracy": round(self.accuracy, 4),
            "field_comparisons": [fc.to_dict() for fc in self.field_comparisons],
        }


NON_NUMERIC_EXCLUDED_FIELDS = {
    "PART_NUMBER", "Mfg_Part_Num", "MANUFACTURER_PART_NUMBER",
    "SKU - MY_PART_NUMBER", "ALTERNATE_PART_NUMBER",
    "MOBILE_DESC", "INVOICE_DESC", "SHORT_DESC", "LONG_DESC1", "RETAIL_DESC", "MARKETING_DESCRIPTION",
    "MFR URL", "Ref URL 1", "Ref URL 2", "Ref URL 3", "Ref URL 4", "Ref URL 5",
    "UPC", "EAN", "GTIN", "UNSPSC", "Product Name", "Classpath", "Dept", "Class", "Fine",
    "BRAND_NAME", "MANUFACTURER_NAME", "TRADE_NAME", "E1_Brand", "Unilog_Brand", "DIB_Brand", "Part_Manuf",
}


def _is_numeric_equivalent(field_name: str, exp: str, act: str) -> bool:
    """Field-aware numeric equivalence comparison (e.g. 5 vs 5.0). Never normalizes MPNs, URLs, or text."""
    if field_name in NON_NUMERIC_EXCLUDED_FIELDS or field_name.startswith("ATTRIBUTE_LABEL") or field_name.startswith("ITEM_FEATURES"):
        return False

    try:
        exp_f = float(exp)
        act_f = float(act)
        return exp_f == act_f
    except (ValueError, TypeError):
        return False


def _normalize_value(val: str) -> str:
    """Basic deterministic normalization for comparison."""
    return val.strip().lower().replace("\u00ae", "").replace("®", "").replace("\u2122", "").replace("™", "")


def _is_empty(val: Any) -> bool:
    """Check if a value is effectively empty."""
    if pd.isna(val):
        return True
    s = str(val).strip()
    return s == "" or s.lower() in ("nan", "none", "null")


def compare_record(
    expected_row: pd.Series,
    actual_row: pd.Series,
    mpn: str,
) -> RecordComparison:
    """Compare a single NS-CIE output record against the golden reference."""
    result = RecordComparison(mfg_part_num=mpn)

    for field_name in COMPARISON_FIELDS:
        expected_val = expected_row.get(field_name)
        actual_val = actual_row.get(field_name)

        exp_empty = _is_empty(expected_val)
        act_empty = _is_empty(actual_val)

        expected_str = "" if exp_empty else str(expected_val).strip()
        actual_str = "" if act_empty else str(actual_val).strip()

        if exp_empty:
            # Expected value is empty — skip from accuracy calculation
            fc = FieldComparison(
                field_name=field_name,
                expected_value=expected_str,
                actual_value=actual_str,
                comparison_type="EXPECTED_EMPTY",
            )
            result.expected_empty += 1
        elif expected_str == actual_str:
            fc = FieldComparison(
                field_name=field_name,
                expected_value=expected_str,
                actual_value=actual_str,
                comparison_type="EXACT_MATCH",
            )
            result.exact_matches += 1
        elif _normalize_value(expected_str) == _normalize_value(actual_str):
            fc = FieldComparison(
                field_name=field_name,
                expected_value=expected_str,
                actual_value=actual_str,
                comparison_type="NORMALIZED_MATCH",
                normalization_rule="case_insensitive_trademark_stripped",
            )
            result.normalized_matches += 1
        elif _is_numeric_equivalent(field_name, expected_str, actual_str):
            fc = FieldComparison(
                field_name=field_name,
                expected_value=expected_str,
                actual_value=actual_str,
                comparison_type="NORMALIZED_MATCH",
                normalization_rule="numeric_representation_equivalence",
            )
            result.normalized_matches += 1
        else:
            fc = FieldComparison(
                field_name=field_name,
                expected_value=expected_str,
                actual_value=actual_str,
                comparison_type="MISMATCH",
            )
            result.mismatches += 1

        result.total_compared_fields += 1
        result.field_comparisons.append(fc)

    return result


def compare_all_golden_records(
    golden_df: pd.DataFrame,
    output_df: pd.DataFrame,
    matched_mpns: list[str],
    golden_key: str = "Mfg_Part_Num",
    output_key: str = "Mfg_Part_Num",
) -> list[RecordComparison]:
    """Compare all matched golden records against NS-CIE output."""
    results: list[RecordComparison] = []

    for mpn in matched_mpns:
        # Find golden record
        golden_mask = golden_df[golden_key].fillna("").str.strip().str.upper() == mpn.upper()
        if not golden_mask.any():
            continue
        golden_row = golden_df.loc[golden_mask].iloc[0]

        # Find output record
        output_mask = output_df[output_key].fillna("").str.strip().str.upper() == mpn.upper()
        if not output_mask.any():
            logger.warning(f"No NS-CIE output found for golden MPN: {mpn}")
            continue
        output_row = output_df.loc[output_mask].iloc[0]

        comparison = compare_record(golden_row, output_row, mpn)
        results.append(comparison)

    return results


def save_golden_comparison_csv(
    comparisons: list[RecordComparison],
    output_path: str | __builtins__,
) -> None:
    """Save golden_comparison.csv with per-field comparison details."""
    from pathlib import Path
    rows: list[dict[str, Any]] = []
    for comp in comparisons:
        for fc in comp.field_comparisons:
            rows.append({
                "Mfg_Part_Num": comp.mfg_part_num,
                **fc.to_dict(),
            })

    df = pd.DataFrame(rows)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
