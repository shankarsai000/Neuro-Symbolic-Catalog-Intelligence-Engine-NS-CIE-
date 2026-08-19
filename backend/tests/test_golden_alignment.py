"""
Regression tests for golden alignment: numeric normalization, description templates, MFR URLs, and attribute metrics.
"""
import pytest
import pandas as pd
from app.benchmark.golden_comparator import compare_record, _is_numeric_equivalent
from app.ai.schemas import ExtractedAttributes, EnrichmentRequest
from app.core.delivery import SchemaMapper, build_channel_descriptions


def test_numeric_normalization_equivalence():
    """Verify numeric normalization equates float and int representations for numeric fields."""
    # Attribute values
    assert _is_numeric_equivalent("ATTRIBUTE_VALUE 3", "5.0", "5") is True
    assert _is_numeric_equivalent("ATTRIBUTE_VALUE 4", "120.0", "120") is True

    # Selling Qty
    assert _is_numeric_equivalent("Selling Qty", "1.0", "1") is True


def test_mpn_and_urls_never_numerically_normalized():
    """Verify that MPNs, URLs, and string identifiers are NEVER numerically normalized."""
    assert _is_numeric_equivalent("Mfg_Part_Num", "5.0", "5") is False
    assert _is_numeric_equivalent("PART_NUMBER", "120.0", "120") is False
    assert _is_numeric_equivalent("MFR URL", "5.0", "5") is False
    assert _is_numeric_equivalent("INVOICE_DESC", "5.0", "5") is False


def test_channel_descriptions_built_from_canonical_facts():
    """Verify channel descriptions render deterministically from canonical attributes."""
    attrs = ExtractedAttributes(
        brand="FRIGIDAIRE®",
        item_type="Dishwasher",
        mpn="PDSH4816AF",
        voltage="120 V",
        mounting="Leg",
        material="Stainless Steel",
        raw_specs={
            "Series": "Professional Series",
            "Number of Wash Cycles": "5",
            "Amperage": "15 A",
            "SoundLevel": "47 dBA",
            "DepthWithDoorOpen": "50-1/4 in",
            "With": "With CleanBoost™",
            "Additional Information": "240 kW-hr Annual Energy",
        },
    )

    descs = build_channel_descriptions("FRIGIDAIRE®", "PDSH4816AF", attrs)

    assert "FRIGIDAIRE®" in descs["short_desc"]
    assert "Professional Series" in descs["short_desc"]
    assert "5-Wash Cycle" in descs["short_desc"] or "5 Wash Cycles" in descs["long_desc"]
    assert "120 V" in descs["long_desc"]
    assert "15 A" in descs["long_desc"]
    assert "47 dBA" in descs["long_desc"]
    assert "Additional Information: 240 kW-hr Annual Energy" in descs["long_desc"]


def test_mfr_url_canonicalization_and_provenance():
    """Verify MFR URL resolution preserves https and canonical brand domains."""
    req = EnrichmentRequest(mfg_part_num="PDSH4816AF", part_desc="Dishwasher")
    attrs = ExtractedAttributes(
        brand="FRIGIDAIRE®",
        item_type="Dishwasher",
        mpn="PDSH4816AF",
        mfr_url="https://www.frigidaire.com/product/PDSH4816AF",
    )

    record = SchemaMapper.map_to_252_column_record(req, "FRIGIDAIRE®", attrs, {})

    assert record["MFR URL"].startswith("https://")
    assert "frigidaire.com" in record["MFR URL"]


def test_compare_record_with_numeric_normalization():
    """Verify compare_record registers NORMALIZED_MATCH for numeric 5 vs 5.0."""
    exp_series = pd.Series({"ATTRIBUTE_LABEL 3": "Number of Wash Cycles", "ATTRIBUTE_VALUE 3": "5.0"})
    act_series = pd.Series({"ATTRIBUTE_LABEL 3": "Number of Wash Cycles", "ATTRIBUTE_VALUE 3": "5"})

    res = compare_record(exp_series, act_series, "TEST-MPN")
    val_fc = next(fc for fc in res.field_comparisons if fc.field_name == "ATTRIBUTE_VALUE 3")

    assert val_fc.comparison_type == "NORMALIZED_MATCH"
    assert val_fc.normalization_rule == "numeric_representation_equivalence"
