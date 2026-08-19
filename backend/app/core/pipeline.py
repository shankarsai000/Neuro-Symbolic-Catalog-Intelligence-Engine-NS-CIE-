from __future__ import annotations

import time
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.manufacturer_sourcing import fetch_official_manufacturer_specs
from app.ai.category_schema import category_detector
from app.ai.extractor import extract_product_specs
from app.ai.neuro_symbolic import neuro_symbolic_validator
from app.ai.schemas import (
    ChannelDescriptions,
    ConfidenceBreakdown,
    EnrichmentRequest,
    EnrichmentResponse,
    ExtractedAttributes,
    FieldProvenance,
    NeuroSymbolicValidationResult,
)
from app.core.confidence import calculate_mathematical_confidence
from app.core.delivery import build_channel_descriptions, generate_252_column_record
from app.core.guardrails import (
    decimal_to_fraction,
    enforce_uom_spacing,
    format_invoice_desc,
)
from app.core.observability import (
    current_batch_id,
    current_product_id,
    current_request_id,
    telemetry_collector,
    trace_stage_async,
    trace_stage_sync,
)
from app.core.sanitizer import clean_placeholders
from app.data.master_repository import master_data_repository
from app.db.models import (
    AuditEvent,
    EnrichmentRun,
    ExtractedAttribute as DBExtractedAttribute,
    Product,
    ReviewQueue,
    Source as DBSource,
)


async def run_enrichment_pipeline(
    request: EnrichmentRequest,
    db: Optional[AsyncSession] = None,
    batch_job_id: Optional[int] = None,
) -> EnrichmentResponse:
    """Execute the end-to-end production NS-CIE pipeline adhering to all mission criteria with full observability:

    1. Input sanitization of placeholder noise.
    2. Master brand resolution against official legal standards.
    3. Category detection and taxonomy schema lookup.
    4. Official manufacturer sourcing (HTTPS-only, domain allowlist, PDF/HTML parsing).
    5. Category-aware LLM / Heuristic extraction with LOV constraints.
    6. Neuro-symbolic validation (deterministic LOVs, synonym normalization, conflict detection).
    7. Multi-channel description generation (Invoice, Mobile, Product Title, Long Desc).
    8. Mathematical confidence scoring (C = 0.40*P + 0.35*L + 0.25*R).
    9. Field-level provenance mapping with evidence snippets.
    10. 252-column Unilog record delivery mapping & persistence.
    """
    start_time = time.perf_counter()
    if batch_job_id is not None:
        current_batch_id.set(batch_job_id)

    # Step 0: Input Record Validation
    if not (request.mfg_part_num and request.mfg_part_num.strip()) and not (request.part_desc and request.part_desc.strip()):
        raise ValueError("EMPTY_INPUT_RECORD: Request contains empty manufacturing part number and part description.")

    # Step 1: Placeholder sanitization & master entity resolution
    with trace_stage_sync("SANITIZATION_AND_BRAND_RESOLUTION", metadata={"mpn": request.mfg_part_num}):
        sanitized_desc = clean_placeholders(request.part_desc) or request.part_desc
        raw_manuf_clean = clean_placeholders(request.raw_manuf)
        raw_brand_clean = clean_placeholders(request.raw_brand)
        canonical_brand, canonical_manufacturer, supplier_name, brand_score = master_data_repository.resolve_entity(
            raw_desc=sanitized_desc,
            mpn=request.mfg_part_num,
            raw_brand=raw_brand_clean,
            raw_manuf=raw_manuf_clean,
        )

    # Step 2: Category Detection & Schema Resolution
    with trace_stage_sync("CATEGORY_DETECTION", metadata={"mpn": request.mfg_part_num}):
        category_schema = category_detector.detect(
            raw_desc=sanitized_desc,
            mpn=request.mfg_part_num,
            manufacturer=canonical_brand,
        )

    # Step 3: Official Manufacturer Sourcing
    mfg_start = time.perf_counter()
    async with trace_stage_async("MANUFACTURER_SOURCING", metadata={"brand": canonical_brand, "mpn": request.mfg_part_num}):
        sourced_evidence = await fetch_official_manufacturer_specs(
            canonical_brand=canonical_brand,
            mpn=request.mfg_part_num,
        )
    mfg_duration_ms = (time.perf_counter() - mfg_start) * 1000.0
    telemetry_collector.record_manufacturer_fetch(
        duration_ms=mfg_duration_ms,
        from_cache=(sourced_evidence.source_type == "CACHE"),
    )

    # Step 4: Category-Aware Extraction
    llm_start = time.perf_counter()
    with trace_stage_sync("EXTRACTION", metadata={"category": category_schema.name, "mpn": request.mfg_part_num}):
        raw_attributes, source_mode = extract_product_specs(
            raw_desc=sanitized_desc,
            manufacturer=canonical_brand or None,
            category=category_schema.name,
            allowed_lovs=list(category_schema.allowed_lovs.get("item_type", [])),
            manufacturer_evidence=sourced_evidence,
            mpn=request.mfg_part_num,
        )
    llm_duration_ms = (time.perf_counter() - llm_start) * 1000.0
    telemetry_collector.record_llm_latency(
        duration_ms=llm_duration_ms,
        is_live_nim=(source_mode == "LIVE_NIM"),
    )

    if canonical_brand:
        raw_attributes.brand = canonical_brand

    # If official manufacturer evidence exists, tag accordingly
    if sourced_evidence.http_status == 200 and source_mode == "LIVE_NIM":
        source_mode = "MANUFACTURER_SOURCE"

    # Step 5: Neuro-Symbolic Validation & Deterministic Synonym Normalization
    with trace_stage_sync("NEURO_SYMBOLIC_VALIDATION", metadata={"category": category_schema.name}):
        validation_result = neuro_symbolic_validator.validate(
            raw_attrs=raw_attributes,
            schema=category_schema,
            manufacturer_evidence=sourced_evidence.evidence_snippets,
        )
        final_attributes = validation_result.normalized_output

    # Step 6: Multi-Channel Description Generation
    with trace_stage_sync("GUARDRAIL_DESCRIPTIONS", metadata={"item_type": final_attributes.item_type}):
        channel_dict = build_channel_descriptions(
            brand=final_attributes.brand or canonical_brand,
            mpn=final_attributes.mpn or request.mfg_part_num,
            attrs=final_attributes,
        )
        channel_desc = ChannelDescriptions(**channel_dict)

    # Step 7: Mathematical Confidence Calculation (Rule 6)
    with trace_stage_sync("CONFIDENCE_SCORING", metadata={"mpn": request.mfg_part_num}):
        confidence_breakdown = calculate_mathematical_confidence(
            extracted_attrs=final_attributes.model_dump(),
            invoice_desc=channel_desc.invoice_desc,
            provenance_score=sourced_evidence.provenance_score,
        )
        if validation_result.needs_review:
            confidence_breakdown.needs_review = True

    # Record HITL decision telemetry
    telemetry_collector.record_hitl_decision(needs_review=confidence_breakdown.needs_review)

    # Step 8: Field-Level Provenance Mapping
    evidence_snippets = sourced_evidence.evidence_snippets

    def _ev_text(key: str, default: str) -> str:
        snippet = evidence_snippets.get(key)
        if isinstance(snippet, dict):
            return str(snippet.get("evidence") or snippet.get("value") or default)
        if isinstance(snippet, str) and snippet:
            return snippet
        return default

    field_confs = confidence_breakdown.field_confidences
    provenance_map = {
        "brand": FieldProvenance(
            value=final_attributes.brand,
            source_url=sourced_evidence.source_url or "distributor_feed",
            source_type=sourced_evidence.source_type,
            evidence=f"Resolved from '{request.raw_manuf}'",
            retrieved_at=sourced_evidence.retrieved_at,
            confidence=field_confs.get("brand", brand_score),
            is_lov_validated=True,
        ).model_dump(),
        "item_type": FieldProvenance(
            value=final_attributes.item_type,
            source_url=sourced_evidence.source_url or "distributor_feed",
            source_type=sourced_evidence.source_type,
            evidence=_ev_text("item_type", f"Extracted from '{sanitized_desc[:60]}'"),
            retrieved_at=sourced_evidence.retrieved_at,
            confidence=field_confs.get("item_type", confidence_breakdown.total_confidence),
            is_lov_validated=master_data_repository.is_valid_lov("item_type", final_attributes.item_type),
        ).model_dump(),
        "voltage": FieldProvenance(
            value=final_attributes.voltage,
            source_url=sourced_evidence.source_url or "distributor_feed",
            source_type=sourced_evidence.source_type,
            evidence=_ev_text("voltage", "Extracted voltage rating"),
            retrieved_at=sourced_evidence.retrieved_at,
            confidence=field_confs.get("voltage", confidence_breakdown.total_confidence),
            is_lov_validated=master_data_repository.is_valid_lov("voltage", final_attributes.voltage),
        ).model_dump(),
        "dimensions": FieldProvenance(
            value=final_attributes.dimensions,
            source_url=sourced_evidence.source_url or "distributor_feed",
            source_type=sourced_evidence.source_type,
            evidence=_ev_text("dimensions", "Converted fractional size"),
            retrieved_at=sourced_evidence.retrieved_at,
            confidence=field_confs.get("dimensions", confidence_breakdown.total_confidence),
            is_lov_validated=True,
        ).model_dump(),
        "material": FieldProvenance(
            value=final_attributes.material,
            source_url=sourced_evidence.source_url or "distributor_feed",
            source_type=sourced_evidence.source_type,
            evidence=_ev_text("material", "Extracted material specification"),
            retrieved_at=sourced_evidence.retrieved_at,
            confidence=field_confs.get("material", confidence_breakdown.total_confidence),
            is_lov_validated=master_data_repository.is_valid_lov("material", final_attributes.material),
        ).model_dump(),
    }

    # Step 9: Static 252-Column Unilog Schema Delivery Mapping
    with trace_stage_sync("SCHEMA_MAPPING", metadata={"mpn": request.mfg_part_num}):
        delivery_record = generate_252_column_record(
            raw_req=request,
            canonical_brand=final_attributes.brand or canonical_brand or "",
            canonical_manufacturer=canonical_manufacturer,
            attrs=final_attributes,
            descriptions=channel_dict,
            confidence=confidence_breakdown.total_confidence,
        )
        telemetry_collector.record_schema_validation(is_valid=(len(delivery_record) == 252))

    execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

    # Step 10: Persistent Database Storage (if DB session active)
    if db is not None:
        try:
            # 1. Product record
            product = Product(
                mfg_part_num=request.mfg_part_num,
                part_desc=request.part_desc,
                raw_manuf=request.raw_manuf,
                canonical_brand=final_attributes.brand or canonical_brand,
                status="completed" if not confidence_breakdown.needs_review else "review_required",
            )
            db.add(product)
            await db.flush()
            current_product_id.set(product.id)

            # 2. Enrichment run record
            run = EnrichmentRun(
                product_id=product.id,
                batch_job_id=batch_job_id,
                source_mode=source_mode,
                confidence_score=confidence_breakdown.total_confidence,
                provenance_score=confidence_breakdown.provenance_score,
                lov_score=confidence_breakdown.lov_match_score,
                rule_score=confidence_breakdown.rule_compliance_score,
                invoice_desc=channel_desc.invoice_desc,
                mobile_desc=channel_desc.mobile_desc,
                product_title=channel_desc.product_title,
                long_desc=channel_desc.long_desc,
                short_desc=channel_desc.short_desc,
                execution_time_ms=execution_time_ms,
            )
            db.add(run)
            await db.flush()

            # 3. Extracted attributes persistence
            for k, prov in provenance_map.items():
                if prov["value"]:
                    attr_rec = DBExtractedAttribute(
                        enrichment_run_id=run.id,
                        attribute_label=k.replace("_", " ").title(),
                        attribute_value=str(prov["value"]),
                        source_url=prov["source_url"],
                        source_type=prov["source_type"],
                        evidence_text=prov["evidence"],
                        confidence=prov["confidence"],
                        is_lov_validated=prov["is_lov_validated"],
                    )
                    db.add(attr_rec)

            # 4. HITL Review Queue insertion if confidence < 0.90
            if confidence_breakdown.needs_review:
                review_item = ReviewQueue(
                    product_id=product.id,
                    enrichment_run_id=run.id,
                    batch_job_id=batch_job_id,
                    field_name="INVOICE_DESC / ATTRIBUTES",
                    original_value=request.part_desc,
                    suggested_value=channel_desc.invoice_desc,
                    current_value=channel_desc.invoice_desc,
                    reason="Confidence score below 90% threshold",
                    confidence=confidence_breakdown.total_confidence,
                    status="PENDING",
                )
                db.add(review_item)

            # 5. Audit Event
            audit = AuditEvent(
                event_type="ENRICHMENT_COMPLETED",
                entity_type="PRODUCT",
                entity_id=request.mfg_part_num,
                payload_json={
                    "confidence": confidence_breakdown.total_confidence,
                    "source_mode": source_mode,
                    "needs_review": confidence_breakdown.needs_review,
                },
            )
            db.add(audit)

        except Exception as e:
            # Non-blocking DB logging failure
            pass

    return EnrichmentResponse(
        mfg_part_num=request.mfg_part_num,
        attributes=final_attributes,
        invoice_desc=channel_desc.invoice_desc,
        channel_descriptions=channel_desc,
        source_mode=source_mode,
        confidence_breakdown=confidence_breakdown,
        confidence_score=confidence_breakdown.total_confidence,
        provenance=provenance_map,
        delivery_record_preview=delivery_record,
        validation_result=validation_result,
        needs_review=confidence_breakdown.needs_review,
    )
