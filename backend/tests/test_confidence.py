from __future__ import annotations

from app.core.confidence import calculate_mathematical_confidence


def test_confidence_calculation_perfect_compliance():
    extracted = {
        "item_type": "Dishwasher",
        "voltage": "120 V",
        "material": "Stainless Steel",
        "mounting": "Built-In",
    }
    invoice = "DISHWASHER BLTLN SST 120 V 50-1/4 IN"
    # Provenance = 1.0 (official manufacturer), LOV match = 1.0, Rule compliance = 1.0
    res = calculate_mathematical_confidence(extracted, invoice, provenance_score=1.0)

    # C = 0.40*1.0 + 0.35*1.0 + 0.25*1.0 = 1.0
    assert res.total_confidence == 1.0
    assert res.provenance_score == 1.0
    assert res.lov_match_score == 1.0
    assert res.rule_compliance_score == 1.0
    assert res.needs_review is False


def test_confidence_calculation_with_violations():
    extracted = {
        "item_type": "UnknownGadget",
        "voltage": "120v",  # glued UOM violation
    }
    # Invoice length > 40 characters violation
    invoice = "THIS IS A VERY LONG INVOICE DESCRIPTION THAT EXCEEDS FORTY CHARACTERS EASILY"
    # Provenance = 0.4 (inferred/heuristic)
    res = calculate_mathematical_confidence(extracted, invoice, provenance_score=0.40)

    # Provenance (0.40 * 0.4 = 0.16)
    # LOV match (0.35 * 0.0 = 0.0)
    # Rule points: Case is upper (+0.25), no unconverted decimal (+0.25) -> Rule score = 0.50 (0.25 * 0.50 = 0.125)
    # Total = 0.16 + 0.0 + 0.125 = 0.285
    assert res.total_confidence < 0.75
    assert res.needs_review is True
