from __future__ import annotations

import logging
from typing import Any, Optional

from app.ai.category_schema import CategorySchema, category_detector
from app.ai.schemas import ExtractedAttributes, ExtractionViolation, NeuroSymbolicValidationResult
from app.core.guardrails import decimal_to_fraction, enforce_uom_spacing
from app.core.sanitizer import clean_placeholders

logger = logging.getLogger(__name__)


class NeuroSymbolicValidator:
    """Combines probabilistic LLM extraction with deterministic master-data constraints and LOV rules."""

    @staticmethod
    def validate(
        raw_attrs: ExtractedAttributes,
        schema: CategorySchema,
        manufacturer_evidence: Optional[dict[str, Any]] = None,
    ) -> NeuroSymbolicValidationResult:
        violations: list[ExtractionViolation] = []
        review_reasons: list[str] = []
        needs_review = False
        passed_lov = True
        passed_rules = True

        raw_dict = raw_attrs.model_dump()
        normalized_dict = dict(raw_dict)

        # 1. Required Attribute Check
        for req_field in schema.required_attributes:
            val = raw_dict.get(req_field)
            if not val or not str(val).strip():
                violations.append(
                    ExtractionViolation(
                        field=req_field,
                        raw_value=None,
                        reason=f"Required attribute '{req_field}' is missing for category '{schema.name}'",
                        action_taken="missing_required",
                    )
                )
                review_reasons.append(f"Missing required field: {req_field}")
                needs_review = True
                passed_rules = False

        # 2. LOV Validation and Deterministic Synonym Normalization
        for field, allowed_set in schema.allowed_lovs.items():
            raw_val = raw_dict.get(field)
            if not raw_val:
                continue

            cleaned_val = clean_placeholders(str(raw_val))
            if not cleaned_val:
                normalized_dict[field] = None
                continue

            # Check if directly matches allowed LOV
            matched_canonical = next(
                (v for v in allowed_set if v.lower() == cleaned_val.lower()),
                None,
            )

            if matched_canonical:
                normalized_dict[field] = matched_canonical
            else:
                # Check deterministic synonym mapping
                synonyms = schema.synonym_mappings.get(field, {})
                syn_match = synonyms.get(cleaned_val.lower())
                if syn_match:
                    normalized_dict[field] = syn_match
                    violations.append(
                        ExtractionViolation(
                            field=field,
                            raw_value=cleaned_val,
                            reason=f"Value '{cleaned_val}' normalized via deterministic synonym rule to '{syn_match}'",
                            action_taken="normalized",
                            suggested_value=syn_match,
                        )
                    )
                else:
                    # Out of vocabulary and no synonym mapping: Reject & Flag
                    passed_lov = False
                    needs_review = True
                    violations.append(
                        ExtractionViolation(
                            field=field,
                            raw_value=cleaned_val,
                            reason=f"Value '{cleaned_val}' is outside allowed vocabulary for {schema.name} and has no synonym mapping",
                            action_taken="rejected",
                        )
                    )
                    review_reasons.append(f"Invalid LOV for {field}: '{cleaned_val}'")

        # 3. UOM & Symbolic Guardrails
        if normalized_dict.get("voltage"):
            spaced_v = enforce_uom_spacing(normalized_dict["voltage"])
            normalized_dict["voltage"] = spaced_v

        if normalized_dict.get("dimensions"):
            spaced_d = enforce_uom_spacing(normalized_dict["dimensions"])
            fractional_d = decimal_to_fraction(spaced_d)
            normalized_dict["dimensions"] = fractional_d

        # 4. Conflicting Source Evidence Detection
        if manufacturer_evidence:
            for spec_key, ev_data in manufacturer_evidence.items():
                if spec_key in normalized_dict and normalized_dict[spec_key]:
                    ev_val = ev_data.get("value") if isinstance(ev_data, dict) else str(ev_data)
                    curr_val = str(normalized_dict[spec_key])
                    # Check for substantive conflict (e.g. 120 V vs 240 V)
                    if ev_val and curr_val and ("120" in ev_val and "240" in curr_val and "120/240" not in curr_val):
                        violations.append(
                            ExtractionViolation(
                                field=spec_key,
                                raw_value=curr_val,
                                reason=f"Extracted value '{curr_val}' conflicts with official manufacturer datasheet evidence '{ev_val}'",
                                action_taken="evidence_conflict",
                                suggested_value=ev_val,
                            )
                        )
                        review_reasons.append(f"Evidence conflict on {spec_key}: LLM={curr_val} vs Sourced={ev_val}")
                        needs_review = True
                        passed_rules = False

        normalized_output = ExtractedAttributes(**normalized_dict)

        return NeuroSymbolicValidationResult(
            category=schema.name,
            is_valid=(passed_lov and passed_rules),
            passed_lov=passed_lov,
            passed_rules=passed_rules,
            violations=violations,
            raw_llm_output=raw_dict,
            normalized_output=normalized_output,
            needs_review=needs_review,
            review_reasons=review_reasons,
        )


neuro_symbolic_validator = NeuroSymbolicValidator()
