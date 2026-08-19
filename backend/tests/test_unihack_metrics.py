"""Tests for metrics module."""
from app.benchmark.golden_comparator import FieldComparison, RecordComparison
from app.benchmark.metrics import (
    compute_field_metrics,
    compute_pipeline_metrics,
    save_metrics,
)


def test_compute_field_metrics():
    comp1 = RecordComparison(
        mfg_part_num="MPN1",
        total_compared_fields=10,
        exact_matches=8,
        normalized_matches=1,
        mismatches=1,
        expected_empty=0,
        field_comparisons=[
            FieldComparison("BRAND_NAME", "DEWALT", "DEWALT", "EXACT_MATCH"),
            FieldComparison("VOLTAGE", "120 V", "120 v", "NORMALIZED_MATCH", "case_insensitive"),
            FieldComparison("COLOR", "Yellow", "Black", "MISMATCH"),
        ],
    )

    metrics = compute_field_metrics([comp1])
    assert metrics.total_golden_records == 1
    assert metrics.exact_match_count == 8
    assert metrics.normalized_match_count == 1
    assert metrics.mismatch_count == 1
    assert metrics.field_accuracy == 0.9  # (8+1)/10 = 0.9
    assert metrics.record_accuracy == 0.0  # not 100%


def test_compute_pipeline_metrics():
    records = [
        {
            "status": "SUCCESS",
            "schema_valid": True,
            "source_mode": "nim",
            "review_required": False,
            "processing_time_ms": 150.0,
        },
        {
            "status": "SUCCESS",
            "schema_valid": True,
            "source_mode": "fallback",
            "review_required": True,
            "processing_time_ms": 250.0,
        },
    ]

    metrics = compute_pipeline_metrics(
        records=records,
        matched_count=2,
        unavailable_count=0,
        total_time_seconds=0.4,
    )
    assert metrics.total_input_records == 2
    assert metrics.total_processed == 2
    assert metrics.total_schema_valid == 2
    assert metrics.nim_count == 1
    assert metrics.fallback_count == 1
    assert metrics.hitl_required_count == 1
    assert metrics.hitl_rate == 0.5
    assert metrics.avg_latency_ms == 200.0


def test_save_metrics(tmp_path):
    f_metrics = compute_field_metrics([])
    p_metrics = compute_pipeline_metrics([], 0, 0)
    f_path, p_path = save_metrics(f_metrics, p_metrics, tmp_path)
    assert f_path.exists()
    assert p_path.exists()
