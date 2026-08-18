from __future__ import annotations

import pytest
from app.core.confidence import (
    calculate_mathematical_confidence,
    resolve_provenance_score,
)


def test_confidence_calculation_perfect_compliance():
    """Verify perfect compliance yields exact 1.000 confidence and AUTO_APPROVED status."""
    extracted_attrs = {
        "item_type": "Dishwasher",
        "voltage": "120 V",
        "material": "Stainless Steel",
        "mounting": "Built-In",
        "dimensions": "50-1/4 in",
    }
    invoice_desc = "PDSH4816AF DISHWSHR SST 120 V 50-1/4 IN"

    breakdown = calculate_mathematical_confidence(
        extracted_attrs=extracted_attrs,
        invoice_desc=invoice_desc,
        provenance_score=1.00,
    )

    # 0.40 * 1.0 + 0.35 * 1.0 + 0.25 * 1.0 = 1.000
    assert breakdown.total_confidence == 1.000
    assert breakdown.provenance_score == 1.000
    assert breakdown.lov_match_score == 1.000
    assert breakdown.rule_compliance_score == 1.000
    assert breakdown.review_tier == "AUTO_APPROVED"
    assert breakdown.needs_review is False
    assert "AUTO_APPROVED" in breakdown.explanation
    assert breakdown.field_confidences["voltage"] == 1.000
    assert breakdown.field_confidences["material"] == 1.000


def test_confidence_calculation_with_violations():
    """Verify non-compliant descriptions and unverified sources yield low confidence and HITL_REQUIRED status."""
    extracted_attrs = {
        "item_type": "InvalidItemType123",
        "voltage": "120v",  # Glued UOM rule violation
        "material": "Unobtanium",  # Invalid LOV
        "dimensions": "50.25 in",  # Unconverted decimal fraction rule violation
    }
    # Invoice desc exceeds 40 chars and has lowercase
    invoice_desc = "this is an extremely long non-compliant invoice description that exceeds 40 characters"

    breakdown = calculate_mathematical_confidence(
        extracted_attrs=extracted_attrs,
        invoice_desc=invoice_desc,
        provenance_score=0.40,
    )

    assert breakdown.total_confidence < 0.75
    assert breakdown.review_tier == "HITL_REQUIRED"
    assert breakdown.needs_review is True
    assert "HITL_REQUIRED" in breakdown.explanation


def test_provenance_score_hierarchy():
    """Verify provenance resolution hierarchy across live, cached, distributor, and unverifiable sources."""
    assert resolve_provenance_score("manufacturer_official_html", http_status=200) == 1.00
    assert resolve_provenance_score("manufacturer_official_pdf", http_status=200) == 1.00
    assert resolve_provenance_score("manufacturer_official_cached") == 0.95
    assert resolve_provenance_score("distributor_feed") == 0.70
    assert resolve_provenance_score("supplier_input_only") == 0.70
    assert resolve_provenance_score("unverifiable") == 0.40


def test_confidence_threshold_tiers():
    """Verify tier classifications: >=0.90 -> AUTO_APPROVED, 0.75-0.89 -> REVIEW, <0.75 -> HITL_REQUIRED."""
    # 1. Auto-approved (>= 0.90)
    res_high = calculate_mathematical_confidence(
        extracted_attrs={"item_type": "Dishwasher", "voltage": "120 V"},
        invoice_desc="DISHWSHR 120 V",
        provenance_score=1.00,
    )
    assert res_high.total_confidence >= 0.90
    assert res_high.review_tier == "AUTO_APPROVED"
    assert res_high.needs_review is False

    # 2. Review (0.75 - 0.89) - distributor feed (0.70) with 100% LOV and 100% rules
    # 0.40 * 0.70 + 0.35 * 1.0 + 0.25 * 1.0 = 0.28 + 0.35 + 0.25 = 0.880
    res_mid = calculate_mathematical_confidence(
        extracted_attrs={"item_type": "Dishwasher", "voltage": "120 V"},
        invoice_desc="DISHWSHR 120 V",
        provenance_score=0.70,
    )
    assert 0.75 <= res_mid.total_confidence < 0.90
    assert res_mid.review_tier == "REVIEW"
    assert res_mid.needs_review is True

    # 3. HITL Required (< 0.75)
    res_low = calculate_mathematical_confidence(
        extracted_attrs={"item_type": "InvalidType"},
        invoice_desc="INVALID",
        provenance_score=0.40,
    )
    assert res_low.total_confidence < 0.75
    assert res_low.review_tier == "HITL_REQUIRED"
    assert res_low.needs_review is True


def test_field_level_confidences_and_explanation():
    """Verify field confidences and explanation string contents."""
    extracted = {
        "brand": "FRIGIDAIRE®",
        "item_type": "Dishwasher",
        "voltage": "120 V",
        "material": "Stainless Steel",
    }
    breakdown = calculate_mathematical_confidence(
        extracted_attrs=extracted,
        invoice_desc="FRIGIDAIRE DISHWSHR SST 120 V",
        provenance_score=0.95,
    )

    assert "brand" in breakdown.field_confidences
    assert "item_type" in breakdown.field_confidences
    assert "voltage" in breakdown.field_confidences
    assert "material" in breakdown.field_confidences

    assert "mathematically derived from" in breakdown.explanation
    assert "Provenance=" in breakdown.explanation
    assert "LOV Match=" in breakdown.explanation
    assert "Rule Compliance=" in breakdown.explanation
