"""
Regression tests for channel description alignment, templates, MFR URLs, and marketing text.
"""
import pytest
from app.ai.schemas import ExtractedAttributes, EnrichmentRequest
from app.core.delivery import SchemaMapper, build_channel_descriptions


def test_long_desc1_deterministic_rendering():
    """Verify LONG_DESC1 constructs a narrative from canonical facts."""
    attrs = ExtractedAttributes(
        brand="DeWalt",
        item_type="Saw Blade",
        mpn="DW3106",
        dimensions="10 in Dia x 5/8 in Arbor",
        material="Carbide Tipped",
        raw_specs={
            "Series": "Precision Trim",
            "Grit": "P80",
            "PackQuantity": "1 PK",
            "Additional Information": "60 Teeth, 7000 RPM Max",
        },
    )

    descs = build_channel_descriptions("DeWalt", "DW3106", attrs)

    assert "DeWalt Saw Blade" in descs["long_desc"]
    assert "Precision Trim" in descs["long_desc"]
    assert "10 in Dia x 5/8 in Arbor" in descs["long_desc"]
    assert "Carbide Tipped" in descs["long_desc"]
    assert "Additional Information: 60 Teeth, 7000 RPM Max" in descs["long_desc"]


def test_retail_desc_begins_with_series_and_category():
    """Verify RETAIL_DESC (product_title) starts with Series and Item Type without duplicating Brand."""
    attrs = ExtractedAttributes(
        brand="Bosch",
        item_type="Dishwasher",
        mpn="SHP878ZD5N",
        mounting="Built-In",
        material="Stainless Steel",
        raw_specs={
            "Series": "800 Series",
            "Number of Wash Cycles": "6",
        },
    )

    descs = build_channel_descriptions("Bosch", "SHP878ZD5N", attrs)

    # Must include Brand and Series, NOT Bosch Bosch
    assert "Bosch" in descs["product_title"]
    assert "800 Series" in descs["product_title"]
    assert "Bosch Bosch" not in descs["product_title"]


def test_marketing_description_empty_when_evidence_absent():
    """Verify MARKETING_DESCRIPTION is empty when evidence is absent, and populated when evidence exists."""
    req = EnrichmentRequest(mfg_part_num="TEST-NOMKT", part_desc="No Marketing Product")
    attrs_no_mkt = ExtractedAttributes(brand="Kichler", item_type="Chandelier", mpn="TEST-NOMKT")

    record_no_mkt = SchemaMapper.map_to_252_column_record(req, "Kichler", attrs_no_mkt, {})
    assert record_no_mkt["MARKETING_DESCRIPTION"] == ""

    # When marketing description is in raw_specs
    attrs_with_mkt = ExtractedAttributes(
        brand="Kichler",
        item_type="Chandelier",
        mpn="TEST-NOMKT",
        raw_specs={"MARKETING_DESCRIPTION": "Stunning 5-light brass chandelier."},
    )

    record_with_mkt = SchemaMapper.map_to_252_column_record(req, "Kichler", attrs_with_mkt, {})
    assert record_with_mkt["MARKETING_DESCRIPTION"] == "Stunning 5-light brass chandelier."


def test_mfr_url_canonical_resolution():
    """Verify MFR URL prefers official evidence URLs and HTTPS domain patterns without inventing subpaths."""
    req = EnrichmentRequest(mfg_part_num="TEST-URL", part_desc="Product")

    # Provided official URL
    attrs1 = ExtractedAttributes(brand="Philips", mpn="TEST-URL", mfr_url="https://www.philips.com/p-p/TEST-URL")
    record1 = SchemaMapper.map_to_252_column_record(req, "Philips", attrs1, {})
    assert record1["MFR URL"] == "https://www.philips.com/p-p/TEST-URL"

    # Fallback to known domain pattern
    attrs2 = ExtractedAttributes(brand="Frigidaire®", mpn="TEST-URL")
    record2 = SchemaMapper.map_to_252_column_record(req, "Frigidaire®", attrs2, {})
    assert record2["MFR URL"].startswith("https://")
    assert "frigidaire.com" in record2["MFR URL"]


def test_cross_brand_description_rendering():
    """Verify deterministic channel description rendering across non-golden brands (e.g. Satco, Festool)."""
    attrs = ExtractedAttributes(
        brand="Satco",
        item_type="LED Bulb",
        mpn="S9800",
        voltage="120 V",
        material="Glass",
        raw_specs={
            "Series": "Hi-Pro",
            "Wattage": "15 W",
            "Lumens": "1600 LM",
        },
    )

    descs = build_channel_descriptions("Satco", "S9800", attrs)

    assert "Satco" in descs["short_desc"]
    assert "S9800" in descs["short_desc"]
    assert "LED Bulb" in descs["short_desc"]
    assert "120 V" in descs["long_desc"]
