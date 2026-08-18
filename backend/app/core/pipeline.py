from __future__ import annotations

from app.agents.resolver import resolve_canonical_brand
from app.agents.scraper import fetch_manufacturer_context
from app.ai.extractor import extract_product_specs
from app.ai.schemas import EnrichmentRequest, EnrichmentResponse, ExtractedAttributes
from app.core.guardrails import (
    decimal_to_fraction,
    enforce_uom_spacing,
    format_invoice_desc,
)
from app.core.sanitizer import clean_placeholders


async def run_enrichment_pipeline(request: EnrichmentRequest) -> EnrichmentResponse:
    """Execute the end-to-end async NS-CIE product catalog enrichment pipeline.

    Step 1: Sanitize raw description and manufacturer input of placeholder noise.
    Step 2: Canonical brand resolution via RapidFuzz matching.
    Step 3: Agentic web sourcing: Async retrieval of manufacturer product datasheet context with in-memory caching.
    Step 4: Zero-shot LLM extraction grounded in datasheet context.
    Step 5: Deterministic guardrails (UOM spacing & fraction formatting) applied on extracted attributes.
    Step 6: Construction of standardized Unilog invoice description (ALL CAPS, <= 40 chars).
    Step 7: Return finalized EnrichmentResponse.
    """
    # Step 1: Placeholder sanitization on input strings
    sanitized_desc = clean_placeholders(request.part_desc) or request.part_desc
    raw_manuf_clean = clean_placeholders(request.raw_manuf)

    # Step 2: Canonical brand resolution (RapidFuzz against Unilog Master Brand list)
    canonical_brand = resolve_canonical_brand(raw_manuf_clean) if raw_manuf_clean else ""

    # Step 3: Agentic Web Sourcing: Retrieve cached or simulated datasheet context
    mfr_context = ""
    if canonical_brand or request.mfg_part_num:
        mfr_context = await fetch_manufacturer_context(
            canonical_brand=canonical_brand,
            mpn=request.mfg_part_num,
        )

    # Step 4: Zero-shot LLM extraction grounded in datasheet context
    raw_attributes, confidence, status = extract_product_specs(
        raw_desc=sanitized_desc,
        manufacturer=canonical_brand or None,
        manufacturer_context=mfr_context or None,
    )

    # Step 5: Enforce strict deterministic guardrails on extracted attributes
    def _guardrail_field(val: str | None) -> str | None:
        if not val:
            return None
        cleaned = clean_placeholders(val)
        if not cleaned:
            return None
        spaced = enforce_uom_spacing(cleaned)
        fractional = decimal_to_fraction(spaced)
        return fractional

    guarded_voltage = _guardrail_field(raw_attributes.voltage)
    guarded_dimensions = _guardrail_field(raw_attributes.dimensions)
    guarded_mounting = clean_placeholders(raw_attributes.mounting)
    guarded_material = clean_placeholders(raw_attributes.material)
    guarded_item_type = clean_placeholders(raw_attributes.item_type)
    guarded_brand = canonical_brand or clean_placeholders(raw_attributes.brand)
    guarded_mpn = clean_placeholders(raw_attributes.mpn) or request.mfg_part_num

    # Guardrail all additional raw_specs values
    guarded_specs: dict[str, str] = {}
    for k, v in raw_attributes.raw_specs.items():
        if isinstance(v, str):
            guarded_specs[k] = _guardrail_field(v) or v
        else:
            guarded_specs[k] = v

    final_attributes = ExtractedAttributes(
        brand=guarded_brand,
        item_type=guarded_item_type,
        mpn=guarded_mpn,
        voltage=guarded_voltage,
        dimensions=guarded_dimensions,
        mounting=guarded_mounting,
        material=guarded_material,
        raw_specs=guarded_specs,
    )

    # Step 6: Construct standardized Unilog invoice description
    # Pattern: [item_type] [mounting] [material] [voltage] [dimensions]
    desc_components: list[str] = []
    if final_attributes.item_type:
        desc_components.append(final_attributes.item_type)
    if final_attributes.mounting:
        desc_components.append(final_attributes.mounting)
    if final_attributes.material:
        mat_token = "SST" if "stainless" in final_attributes.material.lower() else final_attributes.material
        desc_components.append(mat_token)
    if final_attributes.voltage:
        desc_components.append(final_attributes.voltage)
    if final_attributes.dimensions:
        desc_components.append(final_attributes.dimensions)

    raw_invoice_string = " ".join(desc_components) if desc_components else sanitized_desc
    final_invoice_desc = format_invoice_desc(raw_invoice_string)

    # Step 7: Final response
    return EnrichmentResponse(
        mfg_part_num=request.mfg_part_num,
        attributes=final_attributes,
        invoice_desc=final_invoice_desc,
        status=status,
        confidence_score=confidence,
    )
