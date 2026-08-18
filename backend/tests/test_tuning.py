from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

from tuning.evaluate_rlvr import calculate_reward_score, evaluate_batch
from tuning.generate_dataset import generate_chatml_jsonl, load_dataset_dataframe


def test_generate_chatml_jsonl(tmp_path: Path):
    df = pd.DataFrame(
        [
            {
                "Raw_Input": "PDSH4816AF Dishwasher SS 120v",
                "Expected_Invoice_Desc": "DISHWASHER LEG SST 120 V 50-1/4 IN",
                "Expected_Extracted_JSON": {
                    "brand": "FRIGIDAIRE®",
                    "item_type": "Dishwasher",
                    "voltage": "120 V",
                    "dimensions": "50-1/4 in",
                },
            }
        ]
    )

    out_file = tmp_path / "test_train.jsonl"
    count = generate_chatml_jsonl(df, out_file)
    assert count == 1
    assert out_file.exists()

    with open(out_file, "r", encoding="utf-8") as f:
        line = f.readline()
        record = json.loads(line)
        assert "messages" in record
        assert len(record["messages"]) == 3
        assert record["messages"][0]["role"] == "system"
        assert record["messages"][1]["role"] == "user"
        assert record["messages"][2]["role"] == "assistant"

        assistant_json = json.loads(record["messages"][2]["content"])
        assert assistant_json["brand"] == "FRIGIDAIRE®"


def test_calculate_reward_score_compliant():
    compliant = {
        "brand": "FRIGIDAIRE®",
        "item_type": "Dishwasher",
        "voltage": "120 V",
        "dimensions": "50-1/4 in",
        "invoice_desc": "DISHWASHER LEG SST 120 V 50-1/4 IN",
    }
    result = calculate_reward_score(compliant)

    assert result["passed_all_rules"] is True
    assert result["total_compliance_score"] == 1.0
    assert result["rewards"]["invoice_length_reward"] == 1.0
    assert result["rewards"]["invoice_case_reward"] == 1.0
    assert result["rewards"]["uom_spacing_reward"] == 1.0
    assert result["rewards"]["fraction_format_reward"] == 1.0
    assert result["rewards"]["no_placeholders_reward"] == 1.0


def test_calculate_reward_score_non_compliant():
    non_compliant = {
        "brand": "frigid air",
        "voltage": "120v",  # Glued UOM
        "dimensions": "50.25in",  # Raw decimal inches + glued UOM
        "invoice_desc": "Frigidaire Dishwasher with CleanBoost Stainless Steel 120v 50.25in -- Unbranded --",  # Long, lowercase, placeholders
    }
    result = calculate_reward_score(non_compliant)

    assert result["passed_all_rules"] is False
    assert result["total_compliance_score"] < 0.5
    assert result["rewards"]["invoice_length_reward"] == 0.0
    assert result["rewards"]["invoice_case_reward"] == 0.0
    assert result["rewards"]["uom_spacing_reward"] == 0.0
    assert result["rewards"]["fraction_format_reward"] == 0.0
    assert result["rewards"]["no_placeholders_reward"] == 0.0


def test_evaluate_batch():
    batch = [
        {
            "brand": "FRIGIDAIRE®",
            "voltage": "120 V",
            "dimensions": "50-1/4 in",
            "invoice_desc": "DISHWASHER LEG SST 120 V 50-1/4 IN",
        },
        {
            "brand": "unknown",
            "voltage": "120v",
            "dimensions": "50.25in",
            "invoice_desc": "invalid desc that is way too long and not uppercase at all with -- Unbranded --",
        },
    ]

    summary = evaluate_batch(batch)
    assert summary["total_records"] == 2
    assert summary["average_compliance_score"] > 0.0
    assert summary["perfect_compliance_rate"] == "50.0%"
