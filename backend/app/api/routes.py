from __future__ import annotations

import asyncio
from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from app.ai.schemas import (
    BatchEnrichmentRequest,
    BatchEnrichmentResponse,
    BatchItemResult,
    EnrichmentRequest,
    EnrichmentResponse,
)
from app.core.delivery import export_dataframe_to_252_csv, generate_252_column_record
from app.core.guardrails import (
    decimal_to_fraction,
    enforce_uom_spacing,
    format_invoice_desc,
)
from app.core.pipeline import run_enrichment_pipeline
from app.core.sanitizer import clean_placeholders

router = APIRouter()


class HealthResponse(BaseModel):
    status: str = Field(..., examples=["NS-CIE Backend Active"])
    engine: str = Field(default="Neuro-Symbolic Catalog Intelligence Engine (NS-CIE)")
    version: str = Field(default="1.0.0")


class GuardrailsTestRequest(BaseModel):
    raw_text: str = Field(
        ...,
        examples=["50.25in 120v -- Unbranded --"],
        description="Raw input text to process through deterministic guardrails",
    )


class GuardrailsTestResponse(BaseModel):
    raw_text: str
    cleaned_text: str | None
    uom_spaced_text: str
    fraction_converted_text: str
    final_result: str
    invoice_desc_preview: str


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Return backend operational status."""
    return HealthResponse(
        status="NS-CIE Backend Active",
        engine="Neuro-Symbolic Catalog Intelligence Engine (NS-CIE)",
        version="1.0.0",
    )


@router.post("/api/test-guardrails", response_model=GuardrailsTestResponse)
async def test_guardrails(payload: GuardrailsTestRequest) -> GuardrailsTestResponse:
    """Process raw input text through Unilog deterministic guardrails."""
    raw = payload.raw_text

    sanitized = clean_placeholders(raw)
    spaced = enforce_uom_spacing(sanitized) if sanitized is not None else ""
    fractional = decimal_to_fraction(spaced)
    invoice_desc = format_invoice_desc(fractional)

    return GuardrailsTestResponse(
        raw_text=raw,
        cleaned_text=sanitized,
        uom_spaced_text=spaced,
        fraction_converted_text=fractional,
        final_result=fractional,
        invoice_desc_preview=invoice_desc,
    )


@router.post("/api/enrich-single", response_model=EnrichmentResponse)
async def enrich_single(payload: EnrichmentRequest) -> EnrichmentResponse:
    """Execute zero-shot AI extraction, brand resolution, and guardrails for a single catalog record."""
    return await run_enrichment_pipeline(payload)


@router.post("/api/enrich-batch", response_model=BatchEnrichmentResponse)
async def enrich_batch(payload: BatchEnrichmentRequest) -> BatchEnrichmentResponse:
    """Execute asynchronous batch enrichment across multiple catalog records with HITL accuracy metrics."""
    tasks = [run_enrichment_pipeline(item) for item in payload.items]
    responses: list[EnrichmentResponse] = await asyncio.gather(*tasks)

    batch_items: list[BatchItemResult] = []
    high_confidence = 0
    review_needed = 0
    total_conf = 0.0

    for resp in responses:
        conf = resp.confidence_score
        total_conf += conf
        needs_review = conf < 0.90
        if needs_review:
            review_needed += 1
        else:
            high_confidence += 1

        batch_items.append(
            BatchItemResult(
                mfg_part_num=resp.mfg_part_num,
                canonical_brand=resp.attributes.brand or "UNASSIGNED",
                invoice_desc=resp.invoice_desc,
                mobile_desc=resp.channel_descriptions.mobile_desc if resp.channel_descriptions else resp.invoice_desc,
                product_title=resp.channel_descriptions.product_title if resp.channel_descriptions else resp.mfg_part_num,
                confidence_score=round(conf, 3),
                status=resp.status,
                needs_review=needs_review,
                attributes=resp.attributes,
            )
        )

    avg_conf = round(total_conf / len(responses), 3) if responses else 0.0

    return BatchEnrichmentResponse(
        total_items=len(responses),
        high_confidence_count=high_confidence,
        review_needed_count=review_needed,
        average_confidence=avg_conf,
        items=batch_items,
        export_ready=True,
    )


@router.get("/api/export-sample")
async def export_sample_delivery_csv() -> Response:
    """Export benchmark catalog dataset as a downloadable CSV formatted with all 252 delivery headers."""
    sample_records = [
        EnrichmentRequest(
            mfg_part_num="PDSH4816AF",
            part_desc="PDSH4816AF Dishwasher SS 120v 50.25in -- Unbranded --",
            raw_manuf="FRIGIDAIRE",
        ),
        EnrichmentRequest(
            mfg_part_num="WDTS7024RZ",
            part_desc="WDTS7024RZ Dishwasher SS 120v 10a 41dba -- No Unilog Brand --",
            raw_manuf="Whirlpool Corporation",
        ),
        EnrichmentRequest(
            mfg_part_num="49-94-0013",
            part_desc="49-94-0013 Milw 5\"x.045\"x7/8\" Metal Cut Off Disc -- No DIB Brand --",
            raw_manuf="Milwaukee Accessory (4031)",
        ),
        EnrichmentRequest(
            mfg_part_num="DCB518ASTS06G",
            part_desc="DCB518ASTS06G Diablo 1/2\"x18\" Sanding Belt 6pc -- Unbranded --",
            raw_manuf="Freud Inc (2435)",
        ),
        EnrichmentRequest(
            mfg_part_num="5B-332-080",
            part_desc="5B-332-080 HIOLIT 5\" P80 Abrasive Disc -- Unbranded --",
            raw_manuf="Mirka Abrasives Inc (MIRUS)",
        ),
    ]

    tasks = [run_enrichment_pipeline(req) for req in sample_records]
    enriched_results = await asyncio.gather(*tasks)

    delivery_rows = [res.delivery_record_preview for res in enriched_results if res.delivery_record_preview]
    csv_content = export_dataframe_to_252_csv(delivery_rows)

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=NS-CIE_Enriched_Delivery_252_Columns.csv"
        },
    )
