from __future__ import annotations

import pytest
from app.ai.category_schema import CATEGORY_SCHEMAS, category_detector
from app.ai.neuro_symbolic import neuro_symbolic_validator
from app.ai.schemas import EnrichmentRequest, ExtractedAttributes
from app.core.pipeline import run_enrichment_pipeline


def test_valid_lov_acceptance():
    """Verify standard LOV values pass validation with zero violations."""
    schema = CATEGORY_SCHEMAS["Dishwasher"]
    raw_attrs = ExtractedAttributes(
        brand="FRIGIDAIRE®",
        item_type="Dishwasher",
        mpn="PDSH4816AF",
        voltage="120 V",
        dimensions="24 in",
        mounting="Built-In",
        material="Stainless Steel",
    )

    res = neuro_symbolic_validator.validate(raw_attrs, schema)
    assert res.is_valid is True
    assert res.passed_lov is True
    assert res.passed_rules is True
    assert len(res.violations) == 0
    assert res.needs_review is False
    assert res.normalized_output.material == "Stainless Steel"
    assert res.normalized_output.mounting == "Built-In"


def test_deterministic_synonym_normalization():
    """Verify out-of-vocabulary synonyms are deterministically normalized to standard LOVs."""
    schema = CATEGORY_SCHEMAS["Dishwasher"]
    raw_attrs = ExtractedAttributes(
        brand="FRIGIDAIRE®",
        item_type="Dishwasher",
        mpn="PDSH4816AF",
        voltage="120v",
        dimensions="24.25in",
        mounting="built in",
        material="ss",
    )

    res = neuro_symbolic_validator.validate(raw_attrs, schema)
    assert res.is_valid is True
    assert res.needs_review is False
    assert res.normalized_output.material == "Stainless Steel"
    assert res.normalized_output.mounting == "Built-In"
    assert res.normalized_output.voltage == "120 V"
    assert res.normalized_output.dimensions == "24-1/4 in"

    # Check violation records for normalization audit trail
    norm_violations = [v for v in res.violations if v.action_taken == "normalized"]
    assert len(norm_violations) >= 2
    norm_fields = {v.field for v in norm_violations}
    assert "material" in norm_fields
    assert "mounting" in norm_fields


def test_invalid_lov_rejection_and_review():
    """Verify unmapped out-of-vocabulary terms are rejected and flagged for review."""
    schema = CATEGORY_SCHEMAS["Dishwasher"]
    raw_attrs = ExtractedAttributes(
        brand="FRIGIDAIRE®",
        item_type="Dishwasher",
        mpn="PDSH4816AF",
        voltage="120 V",
        dimensions="24 in",
        mounting="Rocket Propelled",
        material="Unobtanium Foam",
    )

    res = neuro_symbolic_validator.validate(raw_attrs, schema)
    assert res.is_valid is False
    assert res.passed_lov is False
    assert res.needs_review is True
    assert len(res.review_reasons) >= 2

    rejected = [v for v in res.violations if v.action_taken == "rejected"]
    assert len(rejected) == 2
    rejected_fields = {v.field for v in rejected}
    assert "mounting" in rejected_fields
    assert "material" in rejected_fields


def test_missing_required_field_detection():
    """Verify missing required category attributes are detected and flagged."""
    schema = CATEGORY_SCHEMAS["Dishwasher"]
    raw_attrs = ExtractedAttributes(
        brand="FRIGIDAIRE®",
        item_type="Dishwasher",
        mpn="PDSH4816AF",
        voltage=None,  # Missing required electrical rating for Dishwasher
        dimensions="24 in",
    )

    res = neuro_symbolic_validator.validate(raw_attrs, schema)
    assert res.is_valid is False
    assert res.passed_rules is False
    assert res.needs_review is True

    missing = [v for v in res.violations if v.action_taken == "missing_required"]
    assert len(missing) >= 1
    assert missing[0].field == "voltage"


def test_conflicting_source_evidence_detection():
    """Verify conflicts between LLM extraction and official manufacturer evidence are flagged."""
    schema = CATEGORY_SCHEMAS["Dishwasher"]
    raw_attrs = ExtractedAttributes(
        brand="FRIGIDAIRE®",
        item_type="Dishwasher",
        mpn="PDSH4816AF",
        voltage="240 V",  # Hallucinated 240 V
        dimensions="24 in",
        material="Stainless Steel",
    )

    manufacturer_evidence = {
        "voltage": {
            "value": "120 V",
            "evidence": "Rated operational voltage: 120 V AC, 60 Hz 15 A",
        }
    }

    res = neuro_symbolic_validator.validate(raw_attrs, schema, manufacturer_evidence=manufacturer_evidence)
    assert res.is_valid is False
    assert res.passed_rules is False
    assert res.needs_review is True

    conflicts = [v for v in res.violations if v.action_taken == "evidence_conflict"]
    assert len(conflicts) == 1
    assert conflicts[0].field == "voltage"
    assert conflicts[0].suggested_value == "120 V"


@pytest.mark.asyncio
async def test_category_detection_and_end_to_end_pipeline():
    """Verify category detection and neuro-symbolic validation execute cleanly end-to-end."""
    req = EnrichmentRequest(
        mfg_part_num="PDSH4816AF",
        part_desc="PDSH4816AF Dishwasher SS 120v 50.25in Built in -- Unbranded --",
        raw_manuf="frigid air",
    )

    res = await run_enrichment_pipeline(req)
    assert res.validation_result is not None
    assert res.validation_result.category == "Dishwasher"
    assert res.attributes.material == "Stainless Steel"
    assert res.attributes.mounting in ["Leg", "Built-In"]
    assert res.attributes.voltage == "120 V"
    assert res.attributes.dimensions in ["50-1/4 in", "24 in W x 24-1/4 in D"]
