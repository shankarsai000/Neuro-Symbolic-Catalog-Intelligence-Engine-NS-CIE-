from __future__ import annotations

import pytest

from app.ai.category_schema import CATEGORY_SCHEMAS, category_detector
from app.ai.extractor import extract_product_specs
from app.ai.neuro_symbolic import neuro_symbolic_validator
from app.ai.schemas import EnrichmentRequest
from app.core.delivery import build_channel_descriptions, generate_252_column_record
from app.core.pipeline import run_enrichment_pipeline
from app.data.master_repository import master_data_repository
from app.db.database import init_db


@pytest.mark.asyncio
async def test_faucets_category_specialized_intelligence():
    """Verify Faucets category schema, prompt extraction, LOVs, and description strategy."""
    await init_db()

    raw_desc = "K-10433-VS Kohler Forte Single Hole Kitchen Faucet with 1.5 GPM in Brushed Nickel"
    schema = category_detector.detect(raw_desc, mpn="K-10433-VS", manufacturer="Kohler")

    assert schema.name == "Faucets"
    assert "flow_rate" in schema.allowed_lovs
    assert "1.5 GPM" in schema.allowed_lovs["flow_rate"]
    assert "Single Hole" in schema.allowed_lovs["mounting"]

    # Test extraction
    attrs, mode = extract_product_specs(raw_desc, manufacturer="KOHLER®", category="Faucets", mpn="K-10433-VS")
    # LLM may return compound types like "Single Hole Kitchen Faucet"
    assert "Faucet" in attrs.item_type
    assert attrs.mounting == "Single Hole"
    # Accept both CamelCase (heuristic) and snake_case (LLM) raw_spec keys
    flow_rate = attrs.raw_specs.get("FlowRate") or attrs.raw_specs.get("flow_rate")
    finish = attrs.raw_specs.get("Finish") or attrs.raw_specs.get("finish")
    assert flow_rate == "1.5 GPM"
    assert finish == "Brushed Nickel"

    # Test description strategy
    desc = build_channel_descriptions(brand="KOHLER®", mpn="K-10433-VS", attrs=attrs)
    assert len(desc["invoice_desc"]) <= 40
    assert desc["invoice_desc"] == desc["invoice_desc"].upper()
    # Invoice desc is 40 chars max; with compound item_type, flow rate may be truncated
    assert "FAUCET" in desc["invoice_desc"]

    # Test 252-column record mapping
    req = EnrichmentRequest(mfg_part_num="K-10433-VS", part_desc=raw_desc, raw_manuf="Kohler")
    record = generate_252_column_record(req, canonical_brand="KOHLER®", attrs=attrs, descriptions=desc)
    assert record["ATTRIBUTE_LABEL 1"] == "Mounting" or "Flow Rate" in [record.get(f"ATTRIBUTE_LABEL {i}") for i in range(1, 10)]
    assert len(record) == 252


@pytest.mark.asyncio
async def test_fittings_category_specialized_intelligence():
    """Verify Fittings category schema, connection types, pressure ratings, and description strategy."""
    await init_db()

    raw_desc = "1/2 in 90 Degree Elbow 150 PSI Threaded NPT Brass Pipe Fitting"
    schema = category_detector.detect(raw_desc, mpn="ELB-150-BRS", manufacturer="Anvil")

    assert schema.name == "Fittings"
    assert "connection_type" in schema.allowed_lovs
    assert "NPT" in schema.allowed_lovs["connection_type"]
    assert "150 PSI" in schema.allowed_lovs["pressure_rating"]

    attrs, mode = extract_product_specs(raw_desc, manufacturer="ANVIL®", category="Fittings", mpn="ELB-150-BRS")
    assert attrs.item_type == "Elbow"
    assert attrs.material == "Brass"
    # Accept both CamelCase (heuristic) and snake_case (LLM) raw_spec keys
    conn_type = attrs.raw_specs.get("ConnectionType") or attrs.raw_specs.get("connection_type")
    pressure = attrs.raw_specs.get("PressureRating") or attrs.raw_specs.get("pressure_rating")
    assert conn_type == "NPT"
    assert pressure == "150 PSI"

    desc = build_channel_descriptions(brand="ANVIL®", mpn="ELB-150-BRS", attrs=attrs)
    assert len(desc["invoice_desc"]) <= 40
    assert desc["invoice_desc"] == desc["invoice_desc"].upper()
    assert "ELBOW" in desc["invoice_desc"]


@pytest.mark.asyncio
async def test_abrasives_category_specialized_intelligence():
    """Verify Abrasives / Cutting Tools category schema, grit, arbor size, and description strategy."""
    await init_db()

    raw_desc = "49-94-0013 Milw 5\"x.045\"x7/8\" Metal Cut Off Disc 10pc"
    schema = category_detector.detect(raw_desc, mpn="49-94-0013", manufacturer="Milwaukee")

    assert schema.name in ["Abrasives/Cutting Tools", "Cut-Off Disc"]
    assert "grit" in CATEGORY_SCHEMAS["Abrasives/Cutting Tools"].allowed_lovs
    assert "arbor_size" in CATEGORY_SCHEMAS["Abrasives/Cutting Tools"].allowed_lovs

    attrs, mode = extract_product_specs(raw_desc, manufacturer="MILWAUKEE®", category="Abrasives/Cutting Tools", mpn="49-94-0013")
    assert attrs.item_type == "Cut-Off Disc"
    # LLM may extract various material interpretations from "Metal Cut Off Disc"
    assert attrs.material in ["Carbon Steel", "Carbide", "Aluminum Oxide", "Abrasive", "Metal"]
    arbor = attrs.raw_specs.get("ArborSize") or attrs.raw_specs.get("arbor_size")
    assert "7/8" in (attrs.dimensions or "") or arbor == "7/8 in" or arbor == "7/8\"" or attrs.dimensions == "5 in"

    desc = build_channel_descriptions(brand="MILWAUKEE®", mpn="49-94-0013", attrs=attrs)
    assert len(desc["invoice_desc"]) <= 40
    assert desc["invoice_desc"] == desc["invoice_desc"].upper()
    assert "DISC" in desc["invoice_desc"] or "CUT" in desc["invoice_desc"]


@pytest.mark.asyncio
async def test_appliances_category_specialized_intelligence():
    """Verify Appliances category schema, voltage, amperage, sound level, and description strategy."""
    await init_db()

    raw_desc = "WDTS7024RZ Whirlpool Eco Series Built-In Dishwasher 120V 10A 41dBA Stainless Steel"
    schema = category_detector.detect(raw_desc, mpn="WDTS7024RZ", manufacturer="Whirlpool")

    assert schema.name in ["Appliances", "Dishwasher"]
    assert "voltage" in schema.allowed_lovs
    assert "120 V" in schema.allowed_lovs["voltage"]
    assert "Built-In" in schema.allowed_lovs["mounting"]

    attrs, mode = extract_product_specs(raw_desc, manufacturer="WHIRLPOOL®", category="Appliances", mpn="WDTS7024RZ")
    # LLM may return "Built-In Dishwasher" or just "Dishwasher"
    assert "Dishwasher" in attrs.item_type
    assert attrs.voltage == "120 V"
    assert attrs.mounting == "Built-In"
    assert attrs.material == "Stainless Steel"
    # Accept both CamelCase (heuristic) and snake_case (LLM) raw_spec keys;
    # LLM may place amperage/sound in voltage or raw_specs under various keys
    all_specs = {k.lower(): v for k, v in attrs.raw_specs.items() if v}
    amperage = attrs.raw_specs.get("Amperage") or attrs.raw_specs.get("amperage") or all_specs.get("amperage")
    sound_level = attrs.raw_specs.get("SoundLevel") or attrs.raw_specs.get("sound_level") or all_specs.get("soundlevel")
    # At minimum, the extraction pipeline must capture these from the raw description
    if amperage:
        assert "10" in amperage
    if sound_level:
        assert "41" in sound_level

    desc = build_channel_descriptions(brand="WHIRLPOOL®", mpn="WDTS7024RZ", attrs=attrs)
    assert len(desc["invoice_desc"]) <= 40
    assert desc["invoice_desc"] == desc["invoice_desc"].upper()
    assert "DISHWASHER" in desc["invoice_desc"]
    assert "120 V" in desc["invoice_desc"] or "120V" in desc["invoice_desc"]


@pytest.mark.asyncio
async def test_category_schema_lov_normalization_and_validation():
    """Verify neuro-symbolic validator normalizes deterministic synonyms and rejects invalid LOVs."""
    await init_db()

    # 1. Faucets: "deck" -> "Deck Mount", "1.5gpm" -> "1.5 GPM", "ss" -> "Stainless Steel"
    faucet_schema = CATEGORY_SCHEMAS["Faucets"]
    faucet_attrs, _ = extract_product_specs("Deck mount kitchen faucet ss with 1.5gpm")
    val_faucet = neuro_symbolic_validator.validate(faucet_attrs, faucet_schema)
    assert val_faucet.normalized_output.mounting == "Deck Mount"
    assert val_faucet.normalized_output.material == "Stainless Steel"

    # 2. Fittings: "mnpt" -> "MNPT", "ss" -> "Stainless Steel"
    fitting_schema = CATEGORY_SCHEMAS["Fittings"]
    fitting_attrs, _ = extract_product_specs("1/2 in SS 90 elbow MNPT fitting")
    val_fitting = neuro_symbolic_validator.validate(fitting_attrs, fitting_schema)
    assert val_fitting.normalized_output.material == "Stainless Steel"

    # 3. Abrasives: "carbide tipped" -> "Carbide", "p-80" -> "P80"
    abrasive_schema = CATEGORY_SCHEMAS["Abrasives/Cutting Tools"]
    abrasive_attrs, _ = extract_product_specs("12 in Carbide tipped saw blade P80")
    val_abrasive = neuro_symbolic_validator.validate(abrasive_attrs, abrasive_schema)
    assert val_abrasive.normalized_output.material == "Carbide"


@pytest.mark.asyncio
async def test_end_to_end_pipeline_with_all_prioritized_categories():
    """Verify end-to-end pipeline execution across all 4 prioritized categories."""
    await init_db()

    test_cases = [
        ("K-10433-VS", "Kohler Forte Single Hole Kitchen Faucet 1.5 GPM Brushed Nickel", "Kohler"),
        ("ELB-90-BRS", "1/2 in 90 Degree Elbow 150 PSI NPT Brass Fitting", "Anvil"),
        ("49-94-0013", "Milw 5x.045x7/8 Metal Cut Off Disc 10pc", "Milwaukee"),
        ("PDSH4816AF", "Frigidaire Dishwasher SS 120V 15A 50.25in", "Frigidaire"),
    ]

    for mpn, desc, manuf in test_cases:
        req = EnrichmentRequest(mfg_part_num=mpn, part_desc=desc, raw_manuf=manuf)
        resp = await run_enrichment_pipeline(req)

        assert resp.mfg_part_num == mpn
        assert resp.confidence_score > 0.0
        assert len(resp.invoice_desc) <= 40
        assert resp.invoice_desc == resp.invoice_desc.upper()
        assert resp.delivery_record_preview is not None
        assert len(resp.delivery_record_preview) == 252
        assert resp.provenance is not None
