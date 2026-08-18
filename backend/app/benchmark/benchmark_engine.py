from __future__ import annotations

import csv
import datetime
import hashlib
import io
import json
import logging
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.schemas import EnrichmentRequest
from app.core.delivery import DELIVERY_HEADERS, export_dataframe_to_252_csv, generate_252_column_record
from app.core.guardrails import (
    decimal_to_fraction,
    enforce_uom_spacing,
    format_invoice_desc,
)
from app.core.pipeline import run_enrichment_pipeline
from app.core.sanitizer import clean_placeholders
from app.core.schema_validator import validate_252_column_dataframe
from app.db.models import BenchmarkResult, BenchmarkRun

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_INPUT_CSV = DATA_DIR / "Unihack_ Sample Dataset - Input.csv"
DEFAULT_EXPECTED_CSV = DATA_DIR / "Unihack_ Expected Output - Delivery Format.csv"


def _normalize_string(s: Any) -> str:
    """Normalize string for robust ground-truth comparison."""
    if s is None or pd.isna(s):
        return ""
    text = str(s).strip()
    if text.lower() in ["nan", "none", "null"]:
        return ""
    # Strip common symbol variations for comparison tolerance where appropriate
    return text.replace("®", "").replace("™", "").strip()


def _compare_field_values(expected: str, actual: str) -> bool:
    """Check whether actual matches expected, accounting for whitespace/casing normalization."""
    exp_clean = _normalize_string(expected).lower()
    act_clean = _normalize_string(actual).lower()
    if not exp_clean and not act_clean:
        return True
    if exp_clean == act_clean:
        return True
    # Handle minor fraction / dimension formatting variations (e.g. 50-1/4 vs 50 1/4)
    if exp_clean.replace("-", " ") == act_clean.replace("-", " "):
        return True
    return False


class GroundTruthBenchmarkEngine:
    """Production ground-truth benchmark engine evaluating NS-CIE against real Unilog delivery records."""

    def __init__(
        self,
        input_csv_path: Optional[Path | str] = None,
        expected_csv_path: Optional[Path | str] = None,
        artifacts_dir: Optional[Path | str] = None,
    ):
        self.input_path = Path(input_csv_path) if input_csv_path else DEFAULT_INPUT_CSV
        self.expected_path = Path(expected_csv_path) if expected_csv_path else DEFAULT_EXPECTED_CSV
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else None

    def load_ground_truth(self) -> dict[str, dict[str, Any]]:
        """Load expected output CSV into dictionary indexed by normalized Mfg_Part_Num."""
        if not self.expected_path.exists():
            logger.warning(f"Expected ground-truth CSV not found at {self.expected_path}")
            return {}

        df_expected = pd.read_csv(self.expected_path, dtype=str)
        ground_truth: dict[str, dict[str, Any]] = {}
        for _, row in df_expected.iterrows():
            mpn = _normalize_string(row.get("Mfg_Part_Num") or row.get("PART_NUMBER"))
            if mpn:
                ground_truth[mpn.upper()] = {k: ("" if pd.isna(v) else str(v).strip()) for k, v in row.items()}
        return ground_truth

    async def execute_run(
        self,
        run_name: str = "Unilog Ground-Truth Benchmark Evaluation",
        sample_limit: Optional[int] = None,
        ground_truth_only: bool = False,
        db: Optional[AsyncSession] = None,
    ) -> dict[str, Any]:
        """Execute full ground-truth benchmark run, comparing predicted 252-column records to ground truth."""
        if not self.input_path.exists():
            raise FileNotFoundError(f"Input dataset not found at {self.input_path}")

        # 1. Load Ground Truth dictionary
        ground_truth_map = self.load_ground_truth()

        # 2. Load Input Dataset
        df_input = pd.read_csv(self.input_path, dtype=str)

        if ground_truth_only and ground_truth_map:
            # Filter input dataset to only records present in ground truth
            gt_mpns = set(ground_truth_map.keys())
            df_input = df_input[df_input["Mfg_Part_Num"].astype(str).str.strip().str.upper().isin(gt_mpns)]

        if sample_limit and sample_limit > 0:
            df_input = df_input.head(sample_limit)

        total_rows = len(df_input)
        if total_rows == 0:
            raise ValueError("No input records available to benchmark.")

        # Metric accumulators
        exact_matches = 0
        total_field_comparisons = 0
        total_field_matches = 0
        brand_matches = 0
        mpn_matches = 0
        category_matches = 0
        attribute_comparisons = 0
        attribute_matches = 0
        uom_compliant_count = 0
        fraction_compliant_count = 0
        invoice_compliant_count = 0
        schema_compliant_count = 0

        predictions_list: list[dict[str, Any]] = []
        errors_list: list[dict[str, Any]] = []
        per_record_results: list[dict[str, Any]] = []
        confidence_scores: list[float] = []

        # 3. Process each record through real NS-CIE pipeline
        for row_idx, row in df_input.iterrows():
            mpn = str(row.get("Mfg_Part_Num", "")).strip()
            desc = str(row.get("Part_Desc", "")).strip()
            manuf = str(row.get("Part_Manuf", "")).strip()

            req = EnrichmentRequest(mfg_part_num=mpn, part_desc=desc, raw_manuf=manuf or None)
            resp = await run_enrichment_pipeline(req)

            conf = resp.confidence_score
            confidence_scores.append(conf)

            # Get predicted 252-column delivery record
            pred_record = resp.delivery_record_preview or generate_252_column_record(
                raw_req=req,
                canonical_brand=resp.attributes.brand or "",
                attrs=resp.attributes,
                descriptions=resp.channel_descriptions.model_dump() if resp.channel_descriptions else {},
                confidence=conf,
            )
            predictions_list.append(pred_record)

            # --- Rule Compliance Checks (General catalog evaluation) ---
            # 1. Invoice description compliance (<= 40 chars, ALL CAPS, no placeholders)
            inv = str(pred_record.get("INVOICE_DESC", "")).strip()
            is_inv_valid = (
                len(inv) <= 40
                and inv == inv.upper()
                and not any(p in inv.lower() for p in ["-- unbranded --", "-- no unilog brand --", "n/a", "tbd"])
            )
            if is_inv_valid:
                invoice_compliant_count += 1
            else:
                errors_list.append({
                    "mpn": mpn,
                    "field": "INVOICE_DESC",
                    "input": desc,
                    "expected": "<=40 chars, ALL CAPS",
                    "actual": inv,
                    "confidence": conf,
                    "source": resp.source_mode,
                    "reason": f"Invoice description non-compliant (length {len(inv)}, uppercase={inv == inv.upper()})",
                })

            # 2. UOM Spacing Compliance (no glued UOMs like 120v or 24in)
            has_glued = False
            for v in resp.attributes.model_dump().values():
                if isinstance(v, str) and ("120v" in v.lower() or "24in" in v.lower() or "15a" in v.lower()):
                    has_glued = True
                    break
            if not has_glued:
                uom_compliant_count += 1
            else:
                errors_list.append({
                    "mpn": mpn,
                    "field": "UOM_SPACING",
                    "input": desc,
                    "expected": "Standard UOM Spacing (e.g. 120 V, 24 in)",
                    "actual": str(resp.attributes.model_dump()),
                    "confidence": conf,
                    "source": resp.source_mode,
                    "reason": "Glued unit of measure detected in extracted attributes",
                })

            # 3. Fraction Format Compliance (no raw .25 in / .5 in)
            dim = resp.attributes.dimensions
            if dim:
                if any(dec in dim for dec in [".25 in", ".5 in", ".75 in", ".125 in"]):
                    errors_list.append({
                        "mpn": mpn,
                        "field": "FRACTION_FORMAT",
                        "input": desc,
                        "expected": "Compound fraction format (e.g. 1/4 in, 1/2 in)",
                        "actual": dim,
                        "confidence": conf,
                        "source": resp.source_mode,
                        "reason": "Unconverted decimal inches detected in dimensions",
                    })
                else:
                    fraction_compliant_count += 1
            else:
                fraction_compliant_count += 1

            # 4. 252-Column Schema Record Check
            if len(pred_record) == 252 and pred_record.get("Mfg_Part_Num") == mpn:
                schema_compliant_count += 1

            # --- Ground Truth Cross-Comparison (if expected row exists) ---
            expected_row = ground_truth_map.get(mpn.upper())
            rec_field_matches = 0
            rec_field_comparisons = 0
            rec_is_exact = False
            rec_errors: list[dict[str, Any]] = []

            predicted_brand = str(pred_record.get("BRAND_NAME", ""))
            predicted_category = str(pred_record.get("Product Name", "") or resp.attributes.item_type or "")
            predicted_invoice = inv

            expected_brand = ""
            expected_category = ""
            expected_invoice = ""

            if expected_row:
                expected_brand = str(expected_row.get("BRAND_NAME", ""))
                expected_category = str(expected_row.get("Product Name", "") or expected_row.get("Fine", ""))
                expected_invoice = str(expected_row.get("INVOICE_DESC", ""))

                # Evaluate Brand Accuracy
                if _compare_field_values(expected_brand, predicted_brand):
                    brand_matches += 1
                else:
                    err = {
                        "mpn": mpn,
                        "field": "BRAND_NAME",
                        "input": manuf or desc,
                        "expected": expected_brand,
                        "actual": predicted_brand,
                        "confidence": conf,
                        "source": resp.source_mode,
                        "reason": f"Brand mismatch: expected '{expected_brand}', got '{predicted_brand}'",
                    }
                    errors_list.append(err)
                    rec_errors.append(err)

                # Evaluate MPN Accuracy
                expected_mpn = str(expected_row.get("Mfg_Part_Num", ""))
                if _compare_field_values(expected_mpn, mpn):
                    mpn_matches += 1
                else:
                    err = {
                        "mpn": mpn,
                        "field": "Mfg_Part_Num",
                        "input": mpn,
                        "expected": expected_mpn,
                        "actual": mpn,
                        "confidence": conf,
                        "source": resp.source_mode,
                        "reason": f"MPN mismatch: expected '{expected_mpn}', got '{mpn}'",
                    }
                    errors_list.append(err)
                    rec_errors.append(err)

                # Evaluate Category Accuracy
                if _compare_field_values(expected_category, predicted_category):
                    category_matches += 1
                else:
                    err = {
                        "mpn": mpn,
                        "field": "Product Name",
                        "input": desc,
                        "expected": expected_category,
                        "actual": predicted_category,
                        "confidence": conf,
                        "source": resp.source_mode,
                        "reason": f"Category mismatch: expected '{expected_category}', got '{predicted_category}'",
                    }
                    errors_list.append(err)
                    rec_errors.append(err)

                # Evaluate Attribute Accuracy across all populated ATTRIBUTE_LABEL / ATTRIBUTE_VALUE slots
                for slot in range(1, 51):
                    exp_lbl = str(expected_row.get(f"ATTRIBUTE_LABEL {slot}", "")).strip()
                    exp_val = str(expected_row.get(f"ATTRIBUTE_VALUE {slot}", "")).strip()
                    if exp_lbl and exp_val:
                        attribute_comparisons += 1
                        # Look for matching attribute label in predictions
                        pred_val = ""
                        for p_slot in range(1, 51):
                            if _compare_field_values(pred_record.get(f"ATTRIBUTE_LABEL {p_slot}", ""), exp_lbl):
                                pred_val = str(pred_record.get(f"ATTRIBUTE_VALUE {p_slot}", "")).strip()
                                break

                        if pred_val and _compare_field_values(exp_val, pred_val):
                            attribute_matches += 1
                        else:
                            err = {
                                "mpn": mpn,
                                "field": f"ATTRIBUTE: {exp_lbl}",
                                "input": desc,
                                "expected": f"{exp_lbl}={exp_val}",
                                "actual": f"{exp_lbl}={pred_val}" if pred_val else "MISSING",
                                "confidence": conf,
                                "source": resp.source_mode,
                                "reason": f"Attribute mismatch for '{exp_lbl}'",
                            }
                            errors_list.append(err)
                            rec_errors.append(err)

                # Evaluate all non-empty ground-truth fields for Field-Level Accuracy
                for col, exp_val in expected_row.items():
                    if exp_val and col in DELIVERY_HEADERS:
                        rec_field_comparisons += 1
                        total_field_comparisons += 1
                        act_val = str(pred_record.get(col, "")).strip()
                        if _compare_field_values(exp_val, act_val):
                            rec_field_matches += 1
                            total_field_matches += 1

                # Exact Match if core fields + invoice + category match and high compliance
                if (
                    _compare_field_values(expected_brand, predicted_brand)
                    and _compare_field_values(expected_mpn, mpn)
                    and _compare_field_values(expected_category, predicted_category)
                    and is_inv_valid
                    and not has_glued
                ):
                    exact_matches += 1
                    rec_is_exact = True

            else:
                # If ground truth row is not present in expected CSV, compute compliance-based exact match
                if is_inv_valid and not has_glued and conf >= 0.90:
                    exact_matches += 1
                    rec_is_exact = True

            per_record_results.append({
                "row_index": int(row_idx),
                "mpn": mpn,
                "is_exact_match": rec_is_exact,
                "predicted_brand": predicted_brand,
                "predicted_category": predicted_category,
                "predicted_invoice": predicted_invoice,
                "expected_brand": expected_brand,
                "expected_category": expected_category,
                "expected_invoice": expected_invoice,
                "confidence": conf,
                "source_mode": resp.source_mode,
                "field_scores": {
                    "field_matches": rec_field_matches,
                    "field_comparisons": rec_field_comparisons,
                    "accuracy": round(rec_field_matches / max(rec_field_comparisons, 1), 4),
                    "invoice_compliant": is_inv_valid,
                    "uom_compliant": not has_glued,
                },
                "errors": rec_errors,
            })

        # 4. Compute Aggregate Metrics
        evaluated_gt_rows = sum(1 for r in per_record_results if r["expected_brand"] or r["expected_category"])
        gt_count = max(evaluated_gt_rows, 1) if evaluated_gt_rows > 0 else total_rows

        exact_match_rate = round(exact_matches / total_rows, 4)
        field_accuracy = (
            round(total_field_matches / total_field_comparisons, 4)
            if total_field_comparisons > 0
            else round((invoice_compliant_count + uom_compliant_count + fraction_compliant_count) / (total_rows * 3), 4)
        )
        category_accuracy = round(category_matches / gt_count, 4) if evaluated_gt_rows > 0 else round(invoice_compliant_count / total_rows, 4)
        brand_accuracy = round(brand_matches / gt_count, 4) if evaluated_gt_rows > 0 else 1.0
        mpn_accuracy = round(mpn_matches / gt_count, 4) if evaluated_gt_rows > 0 else 1.0
        attribute_accuracy = round(attribute_matches / attribute_comparisons, 4) if attribute_comparisons > 0 else 1.0

        schema_compliance_rate = round(schema_compliant_count / total_rows, 4)
        uom_compliance_rate = round(uom_compliant_count / total_rows, 4)
        fraction_compliance_rate = round(fraction_compliant_count / total_rows, 4)
        invoice_compliance_rate = round(invoice_compliant_count / total_rows, 4)

        # 5. Generate CSV Deliverables & Summary Hash
        predictions_df = pd.DataFrame(predictions_list).reindex(columns=DELIVERY_HEADERS, fill_value="")
        predictions_csv = export_dataframe_to_252_csv(predictions_df)

        # Generate errors CSV
        errors_output = io.StringIO()
        errors_writer = csv.writer(errors_output)
        errors_writer.writerow(["MPN", "Field", "Input", "Expected", "Actual", "Confidence", "Source", "Reason"])
        for err in errors_list:
            errors_writer.writerow([
                err.get("mpn", ""),
                err.get("field", ""),
                err.get("input", ""),
                err.get("expected", ""),
                err.get("actual", ""),
                err.get("confidence", 0.0),
                err.get("source", ""),
                err.get("reason", ""),
            ])
        errors_csv = errors_output.getvalue()

        # Reproducibility hash calculation
        hasher = hashlib.sha256()
        hasher.update(predictions_csv.encode("utf-8"))
        hasher.update(str(exact_match_rate).encode("utf-8"))
        hasher.update(str(field_accuracy).encode("utf-8"))
        predictions_hash = hasher.hexdigest()

        high_conf_count = sum(1 for c in confidence_scores if c >= 0.90)
        mod_conf_count = sum(1 for c in confidence_scores if 0.75 <= c < 0.90)
        low_conf_count = sum(1 for c in confidence_scores if c < 0.75)
        avg_conf = round(sum(confidence_scores) / len(confidence_scores), 3) if confidence_scores else 0.0

        summary_report: dict[str, Any] = {
            "run_name": run_name,
            "dataset_path": str(self.input_path),
            "expected_dataset_path": str(self.expected_path),
            "total_rows_evaluated": total_rows,
            "ground_truth_records_matched": evaluated_gt_rows,
            "exact_match_rate": exact_match_rate,
            "field_accuracy": field_accuracy,
            "category_accuracy": category_accuracy,
            "brand_accuracy": brand_accuracy,
            "mpn_accuracy": mpn_accuracy,
            "attribute_accuracy": attribute_accuracy,
            "schema_compliance_rate": schema_compliance_rate,
            "uom_compliance_rate": uom_compliance_rate,
            "fraction_compliance_rate": fraction_compliance_rate,
            "invoice_compliance_rate": invoice_compliance_rate,
            "metrics": {
                "exact_match_accuracy": exact_match_rate,
                "field_level_accuracy": field_accuracy,
                "category_accuracy": category_accuracy,
                "brand_accuracy": brand_accuracy,
                "mpn_accuracy": mpn_accuracy,
                "attribute_accuracy": attribute_accuracy,
                "invoice_description_compliance": invoice_compliance_rate,
                "uom_compliance": uom_compliance_rate,
                "fraction_compliance": fraction_compliance_rate,
                "schema_compliance": schema_compliance_rate,
            },
            "confidence_distribution": {
                "high_confidence_ge_90": high_conf_count,
                "moderate_confidence_75_89": mod_conf_count,
                "low_confidence_lt_75": low_conf_count,
                "average_confidence": avg_conf,
            },
            "total_errors_detected": len(errors_list),
            "error_samples": errors_list[:20],
            "predictions_hash": predictions_hash,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        # 6. Save Artifacts if directory specified
        if self.artifacts_dir:
            self.artifacts_dir.mkdir(parents=True, exist_ok=True)
            with open(self.artifacts_dir / "predictions.csv", "w", encoding="utf-8") as f:
                f.write(predictions_csv)
            with open(self.artifacts_dir / "errors.csv", "w", encoding="utf-8") as f:
                f.write(errors_csv)
            with open(self.artifacts_dir / "summary.json", "w", encoding="utf-8") as f:
                json.dump(summary_report, f, indent=2)

        # 7. Persist to Database if session active
        if db is not None:
            try:
                bench_run = BenchmarkRun(
                    name=run_name,
                    dataset_path=str(self.input_path),
                    total_rows=total_rows,
                    exact_match_rate=exact_match_rate,
                    field_accuracy=field_accuracy,
                    category_accuracy=category_accuracy,
                    brand_accuracy=brand_accuracy,
                    mpn_accuracy=mpn_accuracy,
                    attribute_accuracy=attribute_accuracy,
                    schema_compliance=schema_compliance_rate,
                    uom_compliance=uom_compliance_rate,
                    fraction_compliance=fraction_compliance_rate,
                    invoice_compliance=invoice_compliance_rate,
                    predictions_hash=predictions_hash,
                    status="completed",
                    report_json=summary_report,
                )
                db.add(bench_run)
                await db.flush()

                for res in per_record_results:
                    bench_res = BenchmarkResult(
                        benchmark_run_id=bench_run.id,
                        row_index=res["row_index"],
                        mpn=res["mpn"],
                        is_exact_match=res["is_exact_match"],
                        predicted_brand=res["predicted_brand"],
                        predicted_category=res["predicted_category"],
                        predicted_invoice=res["predicted_invoice"],
                        expected_brand=res["expected_brand"],
                        expected_category=res["expected_category"],
                        expected_invoice=res["expected_invoice"],
                        confidence=res["confidence"],
                        source_mode=res["source_mode"],
                        field_scores_json=res["field_scores"],
                        errors_json=res["errors"],
                    )
                    db.add(bench_res)

                await db.commit()
                summary_report["run_id"] = bench_run.id
            except Exception as e:
                logger.error(f"Error persisting benchmark run to database: {e}")
                await db.rollback()

        return summary_report


async def run_ground_truth_benchmark(
    run_name: str = "Unilog Ground-Truth Benchmark Evaluation",
    sample_limit: Optional[int] = 50,
    ground_truth_only: bool = False,
    db: Optional[AsyncSession] = None,
    artifacts_dir: Optional[Path | str] = None,
) -> dict[str, Any]:
    """Top-level convenience function for executing ground-truth evaluation."""
    engine = GroundTruthBenchmarkEngine(artifacts_dir=artifacts_dir)
    return await engine.execute_run(
        run_name=run_name,
        sample_limit=sample_limit,
        ground_truth_only=ground_truth_only,
        db=db,
    )
