"""
Unit Tests for NS-CIE v2.2-RC2 Hardening: None-Safety, Confidence Calibration, and Telemetry Accounting.
"""

import pytest
from app.core.delivery import build_channel_descriptions
from app.core.confidence import calculate_mathematical_confidence, resolve_provenance_score
from app.benchmark.evaluator import evaluate_llm_metrics

def test_build_channel_descriptions_none_safety_on_color_and_material():
    # Test color present, material None -> must NOT crash with AttributeError
    res = build_channel_descriptions(
        brand="Milwaukee",
        mpn="2745-20",
        attrs={"item_type": "Skylight", "color": "Black", "material": None},
    )
    assert res["invoice_desc"] != ""
    assert res["short_desc"] != ""

def test_confidence_calibration_for_nim_structured_extractions():
    score = calculate_mathematical_confidence(
        extracted_attrs={"item_type": "Dishwasher", "voltage": "120 V", "material": "Stainless Steel"},
        invoice_desc="DISHWASHER BLTLN SST 120V",
        provenance_score=0.70,
        source_type="LIVE_NIM",
    )
    assert score.provenance_score == 0.85
    assert score.total_confidence >= 0.90
    assert score.review_tier == "AUTO_APPROVED"
    assert score.needs_review is False

def test_telemetry_accounting_sum_is_exact():
    mock_tracking = [
        {"source_mode": "LIVE_NIM", "status": "SUCCESS", "llm_attempted": True, "processing_time_ms": 100},
        {"source_mode": "LIVE_NIM", "status": "SUCCESS", "llm_attempted": True, "processing_time_ms": 110},
        {"source_mode": "MANUFACTURER_SOURCE", "status": "SUCCESS", "llm_attempted": True, "processing_time_ms": 120},
        {"source_mode": "OFFLINE_HEURISTIC", "status": "SUCCESS", "llm_attempted": True, "processing_time_ms": 130},
        {"source_mode": "ERROR", "status": "ERROR", "llm_attempted": True, "processing_time_ms": 140},
    ]
    metrics = evaluate_llm_metrics(mock_tracking)
    dist = metrics["source_mode_distribution"]
    total = sum(dist.values())
    assert total == 5
    assert dist["LIVE_NIM"] == 2
    assert dist["MANUFACTURER_SOURCE"] == 1
    assert dist["OFFLINE_HEURISTIC"] == 1
    assert dist["ERROR"] == 1
