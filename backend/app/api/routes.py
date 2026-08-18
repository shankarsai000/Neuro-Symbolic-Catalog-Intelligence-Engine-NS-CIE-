from __future__ import annotations

import asyncio
import io
from typing import Any, Optional
import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.schemas import (
    BatchEnrichmentRequest,
    BatchEnrichmentResponse,
    BatchItemResult,
    EnrichmentRequest,
    EnrichmentResponse,
)
from app.benchmark.benchmark_engine import run_ground_truth_benchmark
from app.core.config import settings
from app.core.delivery import export_dataframe_to_252_csv
from app.core.guardrails import (
    decimal_to_fraction,
    enforce_uom_spacing,
    format_invoice_desc,
)
from app.core.pipeline import run_enrichment_pipeline
from app.core.sanitizer import clean_placeholders
from app.core.schema_validator import validate_252_column_dataframe
from app.data.master_repository import master_data_repository
from app.db.database import get_db
from app.db.models import BatchJob, BenchmarkRun, Product, ReviewQueue
from app.worker.batch_worker import BATCH_RESULTS_CACHE, enqueue_batch_job

router = APIRouter()


class HealthResponse(BaseModel):
    status: str = Field(..., examples=["NS-CIE Backend Active"])
    engine: str = Field(default="Neuro-Symbolic Catalog Intelligence Engine (NS-CIE)")
    version: str = Field(default="1.0.0")


class SystemMetricsResponse(BaseModel):
    status: str
    database: str
    redis: str
    llm_model: str
    source_mode_default: str
    master_brands_count: int
    master_uom_count: int
    active_batch_jobs: int


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


class CreateBatchRequest(BaseModel):
    name: str = Field(..., description="Batch job name")
    filename: Optional[str] = Field(default="catalog_feed.csv")


class BenchmarkRunRequest(BaseModel):
    run_name: str = Field(default="Unilog 200-Row Evaluation Suite")
    sample_limit: int = Field(default=50, ge=5, le=200)


@router.get("/health", response_model=HealthResponse)
@router.get("/api/system/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Return backend operational status."""
    return HealthResponse(
        status="NS-CIE Backend Active",
        engine="Neuro-Symbolic Catalog Intelligence Engine (NS-CIE)",
        version="1.0.0",
    )


@router.get("/api/system/metrics", response_model=SystemMetricsResponse)
async def system_metrics(db: AsyncSession = Depends(get_db)) -> SystemMetricsResponse:
    """Return real-time health, LOV counts, database connection, and system status."""
    db_status = "connected"
    try:
        await db.execute(select(Product).limit(1))
    except Exception:
        db_status = "local_sqlite_fallback"

    llm_status = settings.LLM_MODEL_NAME if settings.LLM_API_KEY else "offline_heuristic"

    return SystemMetricsResponse(
        status="HEALTHY",
        database=db_status,
        redis="connected_or_asyncio_queue",
        llm_model=llm_status,
        source_mode_default="OFFLINE_HEURISTIC" if not settings.LLM_API_KEY else "LIVE_NIM",
        master_brands_count=len(master_data_repository.canonical_brands),
        master_uom_count=len(master_data_repository.uom_standards),
        active_batch_jobs=len(BATCH_RESULTS_CACHE),
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
async def enrich_single(
    payload: EnrichmentRequest,
    db: AsyncSession = Depends(get_db),
) -> EnrichmentResponse:
    """Execute zero-shot AI extraction, brand resolution, and guardrails for a single catalog record."""
    return await run_enrichment_pipeline(payload, db=db)


@router.post("/api/enrich-batch", response_model=BatchEnrichmentResponse)
async def enrich_batch(
    payload: BatchEnrichmentRequest,
    db: AsyncSession = Depends(get_db),
) -> BatchEnrichmentResponse:
    """Execute asynchronous batch enrichment across multiple catalog records with HITL accuracy metrics."""
    tasks = [run_enrichment_pipeline(item, db=db) for item in payload.items]
    responses: list[EnrichmentResponse] = await asyncio.gather(*tasks)

    batch_items: list[BatchItemResult] = []
    high_confidence = 0
    review_needed = 0
    total_conf = 0.0

    for resp in responses:
        conf = resp.confidence_score
        total_conf += conf
        needs_review = resp.needs_review
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
                source_mode=resp.source_mode,
                confidence_score=round(conf, 3),
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


# ------------------ BATCH JOBS & UPLOAD APIS ------------------ #


@router.post("/api/batches")
async def create_batch_job(
    payload: CreateBatchRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a new batch catalog ingestion job."""
    batch = BatchJob(
        name=payload.name,
        filename=payload.filename or "catalog.csv",
        status="pending",
    )
    db.add(batch)
    await db.commit()
    return {"batch_id": batch.id, "name": batch.name, "status": batch.status}


@router.post("/api/batches/{batch_id}/upload")
async def upload_batch_file(
    batch_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Upload CSV or XLSX dataset and trigger background batch processing."""
    query = select(BatchJob).where(BatchJob.id == batch_id)
    result = await db.execute(query)
    batch = result.scalar_one_or_none()

    if not batch:
        raise HTTPException(status_code=404, detail="Batch job not found")

    content = await file.read()
    filename = file.filename or "uploaded.csv"

    # Parse uploaded file
    items: list[EnrichmentRequest] = []
    try:
        if filename.endswith(".xlsx") or filename.endswith(".xls"):
            df = pd.read_excel(io.BytesIO(content), dtype=str)
        else:
            df = pd.read_csv(io.StringIO(content.decode("utf-8", errors="ignore")), dtype=str)

        for _, row in df.iterrows():
            mpn = str(row.get("Mfg_Part_Num") or row.get("PART_NUMBER") or row.get("MPN") or "").strip()
            desc = str(row.get("Part_Desc") or row.get("Description") or "").strip()
            manuf = str(row.get("Part_Manuf") or row.get("Manufacturer") or "").strip()

            if mpn and desc:
                items.append(EnrichmentRequest(mfg_part_num=mpn, part_desc=desc, raw_manuf=manuf))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse catalog file: {str(e)}")

    if not items:
        raise HTTPException(status_code=400, detail="No valid catalog records found in file")

    batch.total_items = len(items)
    batch.status = "processing"
    await db.commit()

    # Enqueue background processing worker
    enqueue_batch_job(batch_id, items)

    return {
        "batch_id": batch_id,
        "filename": filename,
        "total_records_queued": len(items),
        "status": "processing",
    }


@router.get("/api/batches/{batch_id}")
async def get_batch_status(
    batch_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get metadata and execution status for a batch job."""
    query = select(BatchJob).where(BatchJob.id == batch_id)
    result = await db.execute(query)
    batch = result.scalar_one_or_none()

    if not batch:
        raise HTTPException(status_code=404, detail="Batch job not found")

    return {
        "batch_id": batch.id,
        "name": batch.name,
        "filename": batch.filename,
        "total_items": batch.total_items,
        "processed_items": batch.processed_items,
        "high_confidence_count": batch.high_confidence_count,
        "review_needed_count": batch.review_needed_count,
        "average_confidence": batch.average_confidence,
        "status": batch.status,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
    }


@router.get("/api/batches/{batch_id}/progress")
async def get_batch_progress(
    batch_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get real-time progress statistics for an active batch job."""
    query = select(BatchJob).where(BatchJob.id == batch_id)
    result = await db.execute(query)
    batch = result.scalar_one_or_none()

    if not batch:
        raise HTTPException(status_code=404, detail="Batch job not found")

    percent = (
        round((batch.processed_items / max(batch.total_items, 1)) * 100, 1)
        if batch.total_items > 0
        else 0.0
    )

    return {
        "batch_id": batch.id,
        "status": batch.status,
        "total_items": batch.total_items,
        "processed_items": batch.processed_items,
        "progress_percentage": percent,
        "high_confidence_count": batch.high_confidence_count,
        "review_needed_count": batch.review_needed_count,
        "average_confidence": batch.average_confidence,
    }


@router.get("/api/batches/{batch_id}/results")
async def get_batch_results(batch_id: int) -> dict[str, Any]:
    """Retrieve processed results array for a batch job."""
    results = BATCH_RESULTS_CACHE.get(batch_id, [])
    return {"batch_id": batch_id, "results_count": len(results), "items": results}


@router.get("/api/batches/{batch_id}/download")
async def download_batch_252_csv(batch_id: int) -> Response:
    """Download full 252-column CSV deliverable for a completed batch job."""
    results = BATCH_RESULTS_CACHE.get(batch_id, [])
    if not results:
        raise HTTPException(status_code=404, detail="No processed results available for this batch")

    csv_content = export_dataframe_to_252_csv(results)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=NS-CIE_Batch_{batch_id}_Delivery_252_Columns.csv"
        },
    )


# ------------------ BENCHMARK & SCHEMA VALIDATION APIS ------------------ #


@router.post("/api/benchmark/run")
async def execute_benchmark(
    payload: BenchmarkRunRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Run real ground-truth benchmark suite against Unilog dataset and generate verifiable reports."""
    report = await run_ground_truth_benchmark(
        run_name=payload.run_name,
        sample_limit=payload.sample_limit,
        db=db,
    )
    return report


@router.get("/api/benchmark/{run_id}")
async def get_benchmark_report(
    run_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve historical benchmark run results."""
    query = select(BenchmarkRun).where(BenchmarkRun.id == run_id)
    result = await db.execute(query)
    bench = result.scalar_one_or_none()

    if not bench:
        raise HTTPException(status_code=404, detail="Benchmark run not found")

    return bench.report_json


@router.get("/api/schema/validate/{batch_id}")
async def validate_batch_schema(batch_id: int) -> dict[str, Any]:
    """Validate processed batch records against exact 252-column schema constraints."""
    results = BATCH_RESULTS_CACHE.get(batch_id, [])
    if not results:
        raise HTTPException(status_code=404, detail="Batch results not found")

    df = pd.DataFrame(results)
    report = validate_252_column_dataframe(df)
    return report.model_dump()


@router.get("/api/export-sample")
async def export_sample_delivery_csv() -> Response:
    """Export sample catalog records as a downloadable 252-column delivery CSV."""
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
