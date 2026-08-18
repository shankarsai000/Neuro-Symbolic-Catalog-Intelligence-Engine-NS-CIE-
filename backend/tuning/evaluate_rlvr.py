from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Regex detecting numeric values directly glued to alphabetic unit characters (e.g. 120v, 24in)
GLUED_UOM_REGEX = re.compile(
    r"(?<![A-Za-z0-9_])\d+(?:\.\d+)?(?:in|inch|ft|v|volt|a|amp|w|watt|hz|rpm|dba|db|psi|oz|lb|mm|cm|m)\b",
    re.IGNORECASE,
)

# Regex detecting decimal inch notation instead of standard compound fraction
DECIMAL_INCH_REGEX = re.compile(
    r"(?<![A-Za-z0-9_])\d*\.\d+\s*(?:in|inch(?:es)?|\"|in\.)\b",
    re.IGNORECASE,
)

# Regex detecting leftover Unilog placeholder noise
PLACEHOLDER_NOISE_REGEX = re.compile(
    r"--\s*(?:Unbranded|No\s+Unilog\s+Brand|No\s+DIB\s+Brand|Unassigned|Not\s+Applicable|N/A)\s*--",
    re.IGNORECASE,
)


def calculate_reward_score(
    prediction_json: dict[str, Any],
    expected_json: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Calculate verifiable rule-based compliance rewards (RLVR) for an extracted record.

    Verifiable Rules:
    1. invoice_length_reward: +1.0 if 0 < len(INVOICE_DESC) <= 40 chars, else 0.0.
    2. invoice_case_reward: +1.0 if INVOICE_DESC is strictly uppercase, else 0.0.
    3. uom_spacing_reward: +1.0 if no numbers are attached directly to unit letters (e.g. '120 V' vs '120v'), else 0.0.
    4. fraction_format_reward: +1.0 if inch dimensions use compound fractions instead of decimals, else 0.0.
    5. no_placeholders_reward: +1.0 if no placeholder noise (-- Unbranded --, etc.) exists, else 0.0.

    Args:
        prediction_json: The dictionary produced by the model or pipeline.
        expected_json: Optional ground-truth target dictionary for accuracy verification.

    Returns:
        Dictionary containing individual reward values (0.0 to 1.0) and total compliance score.
    """
    # Extract invoice description candidate
    invoice_desc = str(
        prediction_json.get("invoice_desc")
        or prediction_json.get("INVOICE_DESC")
        or ""
    ).strip()

    # Rule 1: Invoice length constraint (<= 40 characters)
    invoice_length_reward = 1.0 if (0 < len(invoice_desc) <= 40) else 0.0

    # Rule 2: Invoice uppercase constraint (ALL CAPS)
    invoice_case_reward = (
        1.0
        if (invoice_desc and invoice_desc == invoice_desc.upper() and any(c.isalpha() for c in invoice_desc))
        else 0.0
    )

    # Stringify fields for cross-field verification
    fields_to_check: list[str] = []
    for k, v in prediction_json.items():
        if k not in ("invoice_desc", "INVOICE_DESC") and isinstance(v, str):
            fields_to_check.append(v)

    combined_attr_text = " ".join(fields_to_check)
    full_prediction_text = json.dumps(prediction_json, ensure_ascii=False)

    # Rule 3: UOM Spacing (Fails on "120v" / "24in", passes on "120 V" / "24 in")
    has_glued_uom = bool(GLUED_UOM_REGEX.search(combined_attr_text or full_prediction_text))
    uom_spacing_reward = 0.0 if has_glued_uom else 1.0

    # Rule 4: Fraction formatting (Compound fractions for inch measurements)
    has_raw_decimal_inches = bool(DECIMAL_INCH_REGEX.search(full_prediction_text))
    fraction_format_reward = 0.0 if has_raw_decimal_inches else 1.0

    # Rule 5: No placeholder noise
    has_placeholders = bool(PLACEHOLDER_NOISE_REGEX.search(full_prediction_text))
    no_placeholders_reward = 0.0 if has_placeholders else 1.0

    # Calculate weighted total compliance score
    rewards = {
        "invoice_length_reward": invoice_length_reward,
        "invoice_case_reward": invoice_case_reward,
        "uom_spacing_reward": uom_spacing_reward,
        "fraction_format_reward": fraction_format_reward,
        "no_placeholders_reward": no_placeholders_reward,
    }

    total_compliance_score = sum(rewards.values()) / len(rewards)

    return {
        "rewards": rewards,
        "total_compliance_score": round(total_compliance_score, 4),
        "total_compliance_percentage": f"{round(total_compliance_score * 100, 2)}%",
        "passed_all_rules": total_compliance_score == 1.0,
    }


def evaluate_batch(
    predictions: list[dict[str, Any]],
    expected_list: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Evaluate a batch of predictions and calculate average compliance statistics."""
    if not predictions:
        return {"total_records": 0, "average_compliance_score": 0.0}

    results = []
    for i, pred in enumerate(predictions):
        exp = expected_list[i] if expected_list and i < len(expected_list) else None
        results.append(calculate_reward_score(pred, exp))

    avg_score = sum(r["total_compliance_score"] for r in results) / len(results)
    pass_all_count = sum(1 for r in results if r["passed_all_rules"])

    return {
        "total_records": len(predictions),
        "average_compliance_score": round(avg_score, 4),
        "average_compliance_percentage": f"{round(avg_score * 100, 2)}%",
        "perfect_compliance_rate": f"{round((pass_all_count / len(predictions)) * 100, 2)}%",
        "sample_evaluations": results[:3],
    }


def main() -> None:
    """Demonstrate evaluation on sample compliant vs non-compliant predictions."""
    print("[INFO] Running RLVR Compliance Evaluation Demo...\n")

    compliant_sample = {
        "brand": "FRIGIDAIRE®",
        "item_type": "Dishwasher",
        "voltage": "120 V",
        "dimensions": "50-1/4 in",
        "invoice_desc": "DISHWASHER LEG SST 120 V 50-1/4 IN",
    }

    non_compliant_sample = {
        "brand": "frigid air",
        "item_type": "Dishwasher",
        "voltage": "120v",
        "dimensions": "50.25in",
        "invoice_desc": "Frigidaire Dishwasher with CleanBoost Stainless Steel 120v 50.25in -- Unbranded --",
    }

    eval_compliant = calculate_reward_score(compliant_sample)
    eval_non_compliant = calculate_reward_score(non_compliant_sample)

    print("--- Compliant Output Evaluation ---")
    print(json.dumps(eval_compliant, indent=2))

    print("\n--- Non-Compliant Output Evaluation ---")
    print(json.dumps(eval_non_compliant, indent=2))


if __name__ == "__main__":
    main()
