from __future__ import annotations

import pytest
import pandas as pd
from pathlib import Path

from app.ai.schemas import EnrichmentRequest
from app.core.pipeline import run_enrichment_pipeline
from app.benchmark.golden_comparator import compare_all_golden_records


@pytest.mark.asyncio
async def test_pdsh4816af_extraction_quality():
    """Verify PDSH4816AF official evidence preservation and extraction quality."""
    req = EnrichmentRequest(
        mfg_part_num="PDSH4816AF",
        part_desc="PDSH4816AF Dishwasher SS - Display Only",
        raw_manuf="Appliance Dealers Cooperative (APPDE)",
    )
    res = await run_enrichment_pipeline(req)

    assert "PDSH4816AF" in res.channel_descriptions.short_desc
    assert "Dishwasher" in res.channel_descriptions.short_desc
    assert res.attributes.brand == "FRIGIDAIRE®"
    assert res.attributes.item_type == "Dishwasher"
    assert res.delivery_record_preview["MANUFACTURER_NAME"] == "Rheem Manufacturing"
    assert res.delivery_record_preview["BRAND_NAME"] == "FRIGIDAIRE®"


@pytest.mark.asyncio
async def test_wdts7024rz_extraction_quality():
    """Verify WDTS7024RZ official evidence preservation and extraction quality."""
    req = EnrichmentRequest(
        mfg_part_num="WDTS7024RZ",
        part_desc="WDTS7024RZ Dishwasher SS - Display Only",
        raw_manuf="Appliance Dealers Cooperative (APPDE)",
    )
    res = await run_enrichment_pipeline(req)

    assert res.attributes.brand == "WHIRLPOOL®"
    assert res.invoice_desc == "DISHWASHER BLTLN SST SST 120V 10A 41DBA"
    assert "Eco Series" in res.channel_descriptions.mobile_desc
    assert "Built-in Mounting" in res.channel_descriptions.short_desc or "Built-In Mounting" in res.channel_descriptions.short_desc
    assert res.delivery_record_preview["MANUFACTURER_NAME"] == "Whirlpool Corporation"
    assert res.delivery_record_preview["BRAND_NAME"] == "WHIRLPOOL®"
    assert res.delivery_record_preview["ATTRIBUTE_LABEL 4"] == "Voltage Rating"
    assert res.delivery_record_preview["ATTRIBUTE_VALUE 4"] == "120"
    assert res.delivery_record_preview["ATTRIBUTE_UOM 4"] == "V"
    assert res.delivery_record_preview["ATTRIBUTE_LABEL 5"] == "Amperage Rating"
    assert res.delivery_record_preview["ATTRIBUTE_VALUE 5"] == "10"
    assert res.delivery_record_preview["ATTRIBUTE_UOM 5"] == "A"
    assert res.delivery_record_preview["ATTRIBUTE_LABEL 12"] == "Sound Level"
    assert res.delivery_record_preview["ATTRIBUTE_VALUE 12"] == "41"
    assert res.delivery_record_preview["ATTRIBUTE_UOM 12"] == "dBA"
    assert res.delivery_record_preview["ITEM_FEATURES_1"] == "3rd rack with extra wash action"


@pytest.mark.asyncio
async def test_golden_eval_accuracy_target():
    """Verify that the 2 golden records achieve >50% (actual ~100%) comparable field accuracy target."""
    golden_path = Path("data/2 datasets/Unihack_ Expected Output - Delivery Format.csv")

    req1 = EnrichmentRequest(
        mfg_part_num="PDSH4816AF",
        part_desc="PDSH4816AF Dishwasher SS - Display Only",
        raw_manuf="Appliance Dealers Cooperative (APPDE)",
    )
    res1 = await run_enrichment_pipeline(req1)

    req2 = EnrichmentRequest(
        mfg_part_num="WDTS7024RZ",
        part_desc="WDTS7024RZ Dishwasher SS - Display Only",
        raw_manuf="Appliance Dealers Cooperative (APPDE)",
    )
    res2 = await run_enrichment_pipeline(req2)

    golden_df = pd.read_csv(golden_path, encoding="utf-8")
    output_df = pd.DataFrame([res1.delivery_record_preview, res2.delivery_record_preview])

    comparisons = compare_all_golden_records(
        golden_df=golden_df,
        output_df=output_df,
        matched_mpns=["PDSH4816AF", "WDTS7024RZ"],
    )

    exact_matches = sum(c.exact_matches for c in comparisons)
    normalized_matches = sum(c.normalized_matches for c in comparisons)
    mismatches = sum(c.mismatches for c in comparisons)

    denom = max(exact_matches + normalized_matches + mismatches, 1)
    accuracy_pct = ((exact_matches + normalized_matches) / denom) * 100.0

    assert accuracy_pct > 50.0, f"Golden field accuracy must exceed 50.0%, got {accuracy_pct:.2f}%"
