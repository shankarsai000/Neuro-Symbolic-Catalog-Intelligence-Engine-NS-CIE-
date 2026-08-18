from __future__ import annotations

import re
from typing import Any, Optional

from app.ai.schemas import ConfidenceBreakdown, FieldProvenance
from app.data.master_repository import master_data_repository


def calculate_mathematical_confidence(
    extracted_attrs: dict[str, Any],
    invoice_desc: str,
    provenance_score: float = 0.70,
) -> ConfidenceBreakdown:
    """Calculate mathematically computed confidence score adhering strictly to Rule 6:

    Formula:
        Confidence = 0.40 * provenance_score + 0.35 * lov_match_score + 0.25 * rule_compliance_score
    """
    # 1. Calculate LOV Match Score (0.0 to 1.0)
    checked_fields = 0
    valid_lov_matches = 0

    item_type = extracted_attrs.get("item_type")
    if item_type:
        checked_fields += 1
        if master_data_repository.is_valid_lov("item_type", str(item_type)):
            valid_lov_matches += 1

    mounting = extracted_attrs.get("mounting")
    if mounting:
        checked_fields += 1
        if master_data_repository.is_valid_lov("mounting", str(mounting)):
            valid_lov_matches += 1

    material = extracted_attrs.get("material")
    if material:
        checked_fields += 1
        if master_data_repository.is_valid_lov("material", str(material)):
            valid_lov_matches += 1

    voltage = extracted_attrs.get("voltage")
    if voltage:
        checked_fields += 1
        if master_data_repository.is_valid_lov("voltage", str(voltage)):
            valid_lov_matches += 1

    lov_match_score = (valid_lov_matches / checked_fields) if checked_fields > 0 else 0.85

    # 2. Calculate Rule Compliance Score (0.0 to 1.0)
    rule_points = 0.0

    # Rule 1: Invoice Description <= 40 chars
    if invoice_desc and len(invoice_desc) <= 40:
        rule_points += 0.25

    # Rule 2: Invoice Description is strictly UPPERCASE
    if invoice_desc and invoice_desc == invoice_desc.upper():
        rule_points += 0.25

    # Rule 3: No glued UOM units (e.g. "120v", "24in")
    glued_uom_regex = re.compile(r"\b\d+(\.\d+)?(in|v|a|w|hz|dba|lbs?|mm|cm)\b", re.IGNORECASE)
    has_glued = False
    for v in extracted_attrs.values():
        if isinstance(v, str) and glued_uom_regex.search(v):
            has_glued = True
            break
    if not has_glued:
        rule_points += 0.25

    # Rule 4: Proper compound fraction formatting
    unconverted_decimal_regex = re.compile(r"\b\d+\.(25|5|75|125|375|625|875|0625|1875)\s*in\b", re.IGNORECASE)
    has_unconverted = False
    for v in extracted_attrs.values():
        if isinstance(v, str) and unconverted_decimal_regex.search(v):
            has_unconverted = True
            break
    if not has_unconverted:
        rule_points += 0.25

    rule_compliance_score = round(rule_points, 3)

    # 3. Aggregate Confidence Formula
    # C = 0.40 * P + 0.35 * L + 0.25 * R
    total_conf = (
        0.40 * provenance_score
        + 0.35 * lov_match_score
        + 0.25 * rule_compliance_score
    )
    total_conf_rounded = round(min(max(total_conf, 0.0), 1.0), 3)
    needs_review = total_conf_rounded < 0.90

    return ConfidenceBreakdown(
        total_confidence=total_conf_rounded,
        provenance_score=round(provenance_score, 3),
        lov_match_score=round(lov_match_score, 3),
        rule_compliance_score=rule_compliance_score,
        needs_review=needs_review,
    )
