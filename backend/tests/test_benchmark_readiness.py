"""
Regression tests for benchmark readiness assessment and source-mode accounting.
"""
import pytest
from app.benchmark.evaluator import compute_readiness_assessment, evaluate_llm_metrics


def test_source_mode_accounting_invariant():
    """Verify that every record belongs to exactly one mutually exclusive terminal source mode."""
    mock_tracking = [
        {"source_mode": "LIVE_NIM", "llm_attempted": True, "processing_time_ms": 1500},
        {"source_mode": "LIVE_NIM", "llm_attempted": True, "processing_time_ms": 1200},
        {"source_mode": "MANUFACTURER_SOURCE", "llm_attempted": True, "processing_time_ms": 800},
        {"source_mode": "OFFLINE_HEURISTIC", "llm_attempted": True, "llm_failed": True, "processing_time_ms": 100},
        {"source_mode": "OFFLINE_HEURISTIC", "llm_attempted": True, "llm_failed": True, "processing_time_ms": 120},
        {"source_mode": "CACHE", "llm_attempted": False, "processing_time_ms": 50},
        {"source_mode": "ERROR", "status": "ERROR", "llm_attempted": True, "processing_time_ms": 200},
    ]

    llm_metrics = evaluate_llm_metrics(mock_tracking)
    dist = llm_metrics["source_mode_distribution"]

    total_accounted = (
        dist["LIVE_NIM"]
        + dist["OFFLINE_HEURISTIC"]
        + dist["MANUFACTURER_SOURCE"]
        + dist["CACHE"]
        + dist["ERROR"]
    )

    assert total_accounted == len(mock_tracking), f"Expected {len(mock_tracking)} accounted records, got {total_accounted}"
    assert dist["LIVE_NIM"] == 2
    assert dist["MANUFACTURER_SOURCE"] == 1
    assert dist["OFFLINE_HEURISTIC"] == 2
    assert dist["CACHE"] == 1
    assert dist["ERROR"] == 1
    assert llm_metrics["successful_llm_requests"] == 3


def test_zero_record_accuracy_cannot_be_production_ready():
    """Verify that 0% golden record accuracy prevents PRODUCTION_READY status."""
    readiness = compute_readiness_assessment(
        processing_success_rate=100.0,
        schema_pass_rate=100.0,
        live_nim_count=94,
        golden_comparison_ran=True,
        strict_field_accuracy=50.89,
        normalized_field_accuracy=51.79,
        exact_record_match_rate=0.0,
        normalized_record_match_rate=0.0,
        in_docker=True,
    )

    assert readiness["overall_status"] != "PRODUCTION_READY", "0% record accuracy must not evaluate to PRODUCTION_READY"
    assert readiness["overall_status"] == "CONDITIONALLY_READY"

    record_eval = next(e for e in readiness["evaluations"] if e["criterion"] == "GROUND_TRUTH_RECORD_ACCURACY")
    assert record_eval["status"] == "FAIL"


def test_production_ready_requires_strict_field_and_record_accuracy():
    """Verify that PRODUCTION_READY is granted only when field accuracy >= 85% and record accuracy >= 50%."""
    readiness = compute_readiness_assessment(
        processing_success_rate=100.0,
        schema_pass_rate=100.0,
        live_nim_count=100,
        golden_comparison_ran=True,
        strict_field_accuracy=90.0,
        normalized_field_accuracy=95.0,
        exact_record_match_rate=50.0,
        normalized_record_match_rate=100.0,
        in_docker=True,
    )

    assert readiness["overall_status"] == "PRODUCTION_READY"
