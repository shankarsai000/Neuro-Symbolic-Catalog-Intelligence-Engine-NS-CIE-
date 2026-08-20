from __future__ import annotations

import re
from typing import Any, Optional

from app.ai.schemas import ConfidenceBreakdown
from app.data.master_repository import master_data_repository

# Provenance score constants based on verification hierarchy
PROVENANCE_SCORES: dict[str, float] = {
    "manufacturer_official_live": 1.00,
    "manufacturer_official_html": 1.00,
    "manufacturer_official_pdf": 1.00,
    "manufacturer_official_cached": 0.95,
    "distributor_feed": 0.70,
    "supplier_input_only": 0.70,
    "unverifiable": 0.40,
}


def resolve_provenance_score(source_type: Optional[str], http_status: Optional[int] = None) -> float:
    """Determine provenance score based on sourcing hierarchy."""
    if not source_type:
        return 0.70

    st_clean = source_type.strip().lower()
    if "official" in st_clean:
        if http_status == 200:
            return 1.00
        return 0.95
    if "nim" in st_clean or "live_nim" in st_clean:
        return 0.85
    if "distributor" in st_clean or "supplier" in st_clean:
        return 0.70
    if "unverifiable" in st_clean or "heuristic" in st_clean:
        return 0.40
    return 0.70


def calculate_mathematical_confidence(
    extracted_attrs: dict[str, Any],
    invoice_desc: str,
    provenance_score: float = 0.70,
    source_type: Optional[str] = None,
) -> ConfidenceBreakdown:
    """Calculate mathematically computed confidence score adhering strictly to the formula:

    Formula:
        Confidence = 0.40 * provenance_score + 0.35 * lov_match_score + 0.25 * rule_compliance_score

    Review Tiers:
        >= 0.90 -> AUTO_APPROVED (needs_review = False)
        0.75 - 0.89 -> REVIEW (needs_review = True)
        < 0.75 -> HITL_REQUIRED (needs_review = True)
    """
    # 1. Resolve Provenance Score
    p_score = provenance_score
    if source_type:
        p_score = resolve_provenance_score(source_type)

    # 2. Calculate LOV Match Score (0.0 to 1.0)
    checked_fields = 0
    valid_lov_matches = 0
    field_lov_status: dict[str, bool] = {}

    for field in ["item_type", "mounting", "material", "voltage"]:
        val = extracted_attrs.get(field)
        if val is not None and str(val).strip():
            checked_fields += 1
            is_valid = master_data_repository.is_valid_lov(field, str(val))
            field_lov_status[field] = is_valid
            if is_valid:
                valid_lov_matches += 1

    lov_match_score = (valid_lov_matches / checked_fields) if checked_fields > 0 else 1.00

    # 3. Calculate Rule Compliance Score (0.0 to 1.0)
    rule_points = 0.0

    # Rule 1: Invoice Description <= 40 chars
    if invoice_desc and len(invoice_desc) <= 40:
        rule_points += 0.25

    # Rule 2: Invoice Description is strictly UPPERCASE
    if invoice_desc and invoice_desc == invoice_desc.upper():
        rule_points += 0.25

    # Rule 3: Standard UOM Spacing (no glued UOMs like "120v", "24in")
    glued_uom_regex = re.compile(r"\b\d+(\.\d+)?(in|v|a|w|hz|dba|lbs?|mm|cm)\b", re.IGNORECASE)
    has_glued = False
    for v in extracted_attrs.values():
        if isinstance(v, str) and glued_uom_regex.search(v):
            has_glued = True
            break
    if not has_glued:
        rule_points += 0.25

    # Rule 4: Proper compound fraction formatting (no raw .25 in, .5 in, etc.)
    unconverted_decimal_regex = re.compile(r"\b\d+\.(25|5|75|125|375|625|875|0625|1875)\s*in\b", re.IGNORECASE)
    has_unconverted = False
    for v in extracted_attrs.values():
        if isinstance(v, str) and unconverted_decimal_regex.search(v):
            has_unconverted = True
            break
    if not has_unconverted:
        rule_points += 0.25

    rule_compliance_score = round(rule_points, 3)

    # 4. Aggregate Mathematical Formula
    # C = 0.40 * P + 0.35 * L + 0.25 * R
    total_conf = (
        0.40 * p_score
        + 0.35 * lov_match_score
        + 0.25 * rule_compliance_score
    )
    total_conf_rounded = round(min(max(total_conf, 0.0), 1.0), 3)

    # 5. Determine Review Tier
    if total_conf_rounded >= 0.90:
        review_tier = "AUTO_APPROVED"
        needs_review = False
    elif total_conf_rounded >= 0.75:
        review_tier = "REVIEW"
        needs_review = True
    else:
        review_tier = "HITL_REQUIRED"
        needs_review = True

    # 6. Compute Field-Level Confidences
    field_confidences: dict[str, float] = {}
    for f in ["brand", "item_type", "voltage", "dimensions", "mounting", "material"]:
        val = extracted_attrs.get(f)
        if val is not None and str(val).strip():
            f_lov = 1.0 if field_lov_status.get(f, True) else 0.0
            f_rule = 1.0
            if f == "dimensions" and has_unconverted:
                f_rule = 0.5
            if f == "voltage" and has_glued:
                f_rule = 0.5
            f_conf = round(0.40 * p_score + 0.35 * f_lov + 0.25 * f_rule, 3)
            field_confidences[f] = f_conf

    # 7. Generate Explainable Summary
    explanation = (
        f"Confidence {total_conf_rounded:.3f} mathematically derived from: "
        f"Provenance={p_score:.3f} (weight 40%), "
        f"LOV Match={lov_match_score:.3f} ({valid_lov_matches}/{checked_fields or 1} attributes valid, weight 35%), "
        f"Rule Compliance={rule_compliance_score:.3f} (weight 25%). "
        f"Tier: {review_tier}."
    )

    return ConfidenceBreakdown(
        total_confidence=total_conf_rounded,
        provenance_score=round(p_score, 3),
        lov_match_score=round(lov_match_score, 3),
        rule_compliance_score=rule_compliance_score,
        review_tier=review_tier,
        needs_review=needs_review,
        explanation=explanation,
        field_confidences=field_confidences,
    )
