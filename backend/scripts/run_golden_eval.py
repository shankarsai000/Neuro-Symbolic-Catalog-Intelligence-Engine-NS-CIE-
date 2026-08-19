from __future__ import annotations

import asyncio
import csv
import json
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from app.ai.schemas import EnrichmentRequest
from app.benchmark.golden_comparator import (
    compare_all_golden_records,
    save_golden_comparison_csv,
)
from app.core.pipeline import run_enrichment_pipeline

logger = logging.getLogger(__name__)

GOLDEN_INPUT_PATH = Path("data/2 datasets/Unihack_ Sample Dataset - Input.csv")
GOLDEN_OUTPUT_PATH = Path("data/2 datasets/Unihack_ Expected Output - Delivery Format.csv")


async def run_golden_evaluation() -> dict[str, Any]:
    print("==================================================")
    print("NS-CIE — EXTRACTION QUALITY 2.0 GOLDEN EVALUATION")
    print("==================================================")

    # 1. Load input dataset for PDSH4816AF and WDTS7024RZ
    df_in = pd.read_csv(GOLDEN_INPUT_PATH)
    target_mpns = ["PDSH4816AF", "WDTS7024RZ"]
    target_rows = df_in[df_in["Mfg_Part_Num"].isin(target_mpns)].to_dict("records")

    print(f"Loaded {len(target_rows)} golden input records.")

    # 2. Execute through full production pipeline
    pipeline_records = []

    for row in target_rows:
        mpn = str(row["Mfg_Part_Num"]).strip()
        part_desc = str(row.get("Part_Desc", ""))
        raw_manuf = str(row.get("Part_Manuf", ""))
        e1_brand = str(row.get("E1_Brand", ""))
        unilog_brand = str(row.get("Unilog_Brand", ""))
        dib_brand = str(row.get("DIB_Brand", ""))

        req = EnrichmentRequest(
            mfg_part_num=mpn,
            part_desc=part_desc,
            raw_manuf=raw_manuf,
            e1_brand=e1_brand,
            unilog_brand=unilog_brand,
            dib_brand=dib_brand,
        )

        resp = await run_enrichment_pipeline(req)
        pipeline_records.append(resp.delivery_record_preview)

        print(f"\n[RECORD PROCESSED] MPN: {mpn}")
        print(f"  BRAND_NAME: {resp.attributes.brand}")
        print(f"  INVOICE_DESC: {resp.invoice_desc}")
        print(f"  MOBILE_DESC: {resp.channel_descriptions.mobile_desc}")
        print(f"  SHORT_DESC: {resp.channel_descriptions.short_desc}")

    # 3. Evaluate against Golden Output
    golden_df = pd.read_csv(GOLDEN_OUTPUT_PATH, encoding="utf-8")
    output_df = pd.DataFrame(pipeline_records)

    record_comparisons = compare_all_golden_records(
        golden_df=golden_df,
        output_df=output_df,
        matched_mpns=target_mpns,
    )

    # 4. Compute metrics
    total_compared_fields = sum(c.total_compared_fields for c in record_comparisons)
    exact_matches = sum(c.exact_matches for c in record_comparisons)
    normalized_matches = sum(c.normalized_matches for c in record_comparisons)
    mismatches = sum(c.mismatches for c in record_comparisons)
    expected_empty = sum(c.expected_empty for c in record_comparisons)

    comparable_denom = max(exact_matches + normalized_matches + mismatches, 1)
    strict_acc = round((exact_matches / comparable_denom) * 100.0, 2)
    norm_acc = round(((exact_matches + normalized_matches) / comparable_denom) * 100.0, 2)

    # 5. Write output files
    out_dir = Path("data/benchmark_runs/extraction_quality_2_0")
    out_dir.mkdir(parents=True, exist_ok=True)
    golden_reports_dir = out_dir / "golden_product_reports"
    golden_reports_dir.mkdir(parents=True, exist_ok=True)

    # A. golden_comparison.csv
    comp_file = out_dir / "golden_comparison.csv"
    save_golden_comparison_csv(record_comparisons, str(comp_file))

    # Copy to root benchmark directory
    root_comp_file = Path("data/benchmark_runs/golden_comparison.csv")
    root_comp_file.parent.mkdir(parents=True, exist_ok=True)
    save_golden_comparison_csv(record_comparisons, str(root_comp_file))

    # B. Product reports JSON
    product_reports = []
    for rc in record_comparisons:
        mpn = rc.mfg_part_num
        p_report = {
            "mfg_part_num": mpn,
            "exact_record_match": (rc.mismatches == 0 and rc.normalized_matches == 0),
            "normalized_record_match": (rc.mismatches == 0),
            "fields_evaluated_count": len(rc.field_comparisons),
            "exact_matches": rc.exact_matches,
            "normalized_matches": rc.normalized_matches,
            "mismatches": rc.mismatches,
            "expected_empty": rc.expected_empty,
            "strict_accuracy_pct": round((rc.exact_matches / max(rc.exact_matches + rc.normalized_matches + rc.mismatches, 1)) * 100.0, 2),
            "normalized_accuracy_pct": round(((rc.exact_matches + rc.normalized_matches) / max(rc.exact_matches + rc.normalized_matches + rc.mismatches, 1)) * 100.0, 2),
            "fields": [
                {
                    "field_name": fc.field_name,
                    "expected": fc.expected_value,
                    "actual": fc.actual_value,
                    "status": fc.comparison_type,
                    "normalization_rule": fc.normalization_rule,
                }
                for fc in rc.field_comparisons
            ],
        }
        product_reports.append(p_report)
        p_file = golden_reports_dir / f"{mpn}.json"
        with open(p_file, "w", encoding="utf-8") as f:
            json.dump(p_report, f, indent=2)

    # C. Attribute precision, recall (completeness <= 100%), and F1 calculation
    attribute_metrics = {}
    for report in product_reports:
        mpn = report["mfg_part_num"]
        expected_fields = [f for f in report.get("fields", []) if f.get("expected") != ""]
        expected_pop = len(expected_fields)
        correct = sum(1 for f in expected_fields if f.get("status") in ["EXACT_MATCH", "NORMALIZED_MATCH"])
        incorrect = sum(1 for f in expected_fields if f.get("status") == "MISMATCH")
        actual_pop = sum(1 for f in report.get("fields", []) if f.get("actual") != "")

        missing_attrs = max(0, expected_pop - correct)
        extra_attrs = max(0, actual_pop - expected_pop)

        precision = round((correct / max(actual_pop, 1)) * 100.0, 2)
        recall = round((correct / max(expected_pop, 1)) * 100.0, 2)
        f1 = round((2 * precision * recall / max(precision + recall, 1e-6)), 2)

        attribute_metrics[mpn] = {
            "expected_attributes": expected_pop,
            "actual_attributes": actual_pop,
            "correct_attributes": correct,
            "missing_attributes": missing_attrs,
            "extra_attributes": extra_attrs,
            "incorrect_attributes": incorrect,
            "precision_pct": precision,
            "recall_completeness_pct": recall,
            "f1_score_pct": f1,
        }

    # Summary JSON
    summary = {
        "strict_field_accuracy_pct": strict_acc,
        "normalized_field_accuracy_pct": norm_acc,
        "total_compared_fields": total_compared_fields,
        "exact_matches": exact_matches,
        "normalized_matches": normalized_matches,
        "mismatches": mismatches,
        "expected_empty": expected_empty,
        "attribute_metrics": attribute_metrics,
        "product_reports_dir": str(golden_reports_dir),
        "comparison_file": str(comp_file),
    }

    summary_file = out_dir / "summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n==================================================")
    print("GOLDEN EVALUATION RESULTS SUMMARY")
    print("==================================================")
    print(f"Strict Field Accuracy:     {strict_acc:.2f}%")
    print(f"Normalized Field Accuracy: {norm_acc:.2f}%")

    for mpn, am in attribute_metrics.items():
        print(f"\n{mpn} Attribute Quality Metrics:")
        print(f"  Expected Attributes: {am['expected_attributes']}")
        print(f"  Actual Attributes:   {am['actual_attributes']}")
        print(f"  Correct Attributes:  {am['correct_attributes']}")
        print(f"  Missing Attributes:  {am['missing_attributes']}")
        print(f"  Extra Attributes:    {am['extra_attributes']}")
        print(f"  Incorrect:           {am['incorrect_attributes']}")
        print(f"  Precision %:         {am['precision_pct']}%")
        print(f"  Recall (Completeness) %: {am['recall_completeness_pct']}%")
        print(f"  F1 Score %:          {am['f1_score_pct']}%")

    print("\nGenerated Artifacts:")
    print(f"  - {comp_file}")
    for report in product_reports:
        mpn = report["mfg_part_num"]
        print(f"  - {golden_reports_dir}/{mpn}.json")

    return summary


if __name__ == "__main__":
    asyncio.run(run_golden_evaluation())
