from __future__ import annotations

import asyncio
from datetime import datetime, timezone
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
from app.db.models import BatchJob, BenchmarkResult, BenchmarkRun, Product, ReviewQueue
from app.worker.batch_worker import BATCH_RESULTS_CACHE, enqueue_batch_job, job_queue_manager

router = APIRouter()


from app.ai.nvidia_client import model_health_check


from app.core.observability import evaluate_system_health, telemetry_collector


class ComponentHealth(BaseModel):
    status: str
    details: Optional[dict[str, Any]] = None


class HealthResponse(BaseModel):
    status: str = Field(..., examples=["HEALTHY", "DEGRADED", "UNHEALTHY"])
    engine: str = Field(default="Neuro-Symbolic Catalog Intelligence Engine (NS-CIE)")
    version: str = Field(default="1.0.0")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    components: dict[str, Any] = Field(
        default_factory=dict,
        description="Distinguished status for database, redis, worker, llm, and manufacturer sourcing",
    )
    nvidia_nim: Optional[dict[str, Any]] = Field(default=None, description="NVIDIA NIM model health & discovery")


class SystemMetricsResponse(BaseModel):
    status: str
    database: str
    redis: str
    llm_model: str
    source_mode_default: str
    master_brands_count: int
    master_uom_count: int
    active_batch_jobs: int
    nvidia_nim: Optional[dict[str, Any]] = None
    telemetry: Optional[dict[str, Any]] = None


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
    run_name: str = Field(default="Unilog Ground-Truth Evaluation Suite")
    sample_limit: Optional[int] = Field(default=50, ge=1, le=1000)
    ground_truth_only: bool = Field(default=False, description="Filter specifically to ground-truth records")


@router.get("/health", response_model=HealthResponse)
@router.get("/api/system/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Return backend operational status with component-level differentiation (database, redis, worker, llm, manufacturer_sourcing)."""
    health_data = await evaluate_system_health()
    nim_status = await model_health_check.check_health()
    return HealthResponse(
        status=health_data["status"],
        engine="Neuro-Symbolic Catalog Intelligence Engine (NS-CIE)",
        version="1.0.0",
        timestamp=health_data["timestamp"],
        components=health_data["components"],
        nvidia_nim=nim_status,
    )


@router.get("/api/system/metrics", response_model=SystemMetricsResponse)
async def system_metrics(db: AsyncSession = Depends(get_db)) -> SystemMetricsResponse:
    """Return real-time telemetry metrics, latencies, cache rates, and system status."""
    db_status = "connected"
    try:
        await db.execute(select(Product).limit(1))
    except Exception:
        db_status = "local_sqlite_fallback"

    nim_health = await model_health_check.check_health()
    llm_status = settings.nvidia_model if settings.nvidia_api_key else "offline_heuristic"
    telemetry_snapshot = telemetry_collector.get_metrics_snapshot()

    return SystemMetricsResponse(
        status="HEALTHY",
        database=db_status,
        redis="connected_or_asyncio_queue",
        llm_model=llm_status,
        source_mode_default="OFFLINE_HEURISTIC" if not settings.nvidia_api_key else "LIVE_NIM",
        master_brands_count=len(master_data_repository.canonical_brands),
        master_uom_count=len(master_data_repository.uom_standards),
        active_batch_jobs=len(BATCH_RESULTS_CACHE),
        nvidia_nim=nim_health,
        telemetry=telemetry_snapshot,
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

MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB limit
ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}


def _decode_csv_bytes(content: bytes) -> str:
    """Multi-encoding decoder for robust CSV ingestion."""
    for enc in ["utf-8-sig", "utf-8", "cp1252", "iso-8859-1", "latin1"]:
        try:
            return content.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("utf-8", errors="replace")


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
    """Upload CSV or XLSX dataset, validate encoding & schema, and trigger background chunked processing."""
    query = select(BatchJob).where(BatchJob.id == batch_id)
    result = await db.execute(query)
    batch = result.scalar_one_or_none()

    if not batch:
        raise HTTPException(status_code=404, detail="Batch job not found")

    filename = file.filename or "uploaded.csv"
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file extension '{ext}'. Only CSV and Excel (.xlsx, .xls) files are supported.",
        )

    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="File size exceeds maximum 50 MB upload limit")

    # Parse uploaded file with multi-encoding resilience
    items: list[EnrichmentRequest] = []
    seen_mpns: set[str] = set()
    duplicate_count = 0
    malformed_count = 0

    try:
        if ext in [".xlsx", ".xls"]:
            df = pd.read_excel(io.BytesIO(content), dtype=str)
        else:
            decoded_text = _decode_csv_bytes(content)
            df = pd.read_csv(io.StringIO(decoded_text), dtype=str)

        def _clean_cell(val: Any) -> str:
            if pd.isna(val):
                return ""
            s = str(val).strip()
            if s.lower() in ["nan", "none", "null"]:
                return ""
            return s

        for row_idx, row in df.iterrows():
            mpn = _clean_cell(row.get("Mfg_Part_Num") or row.get("PART_NUMBER") or row.get("MPN") or row.get("Part_Number"))
            desc = _clean_cell(row.get("Part_Desc") or row.get("Description") or row.get("PART_DESC"))
            manuf = _clean_cell(row.get("Part_Manuf") or row.get("Manufacturer") or row.get("PART_MANUF"))

            # Handle malformed / empty rows
            if not mpn and not desc:
                malformed_count += 1
                continue

            if not mpn:
                mpn = f"AUTO-GEN-{row_idx + 1}"
            if not desc:
                desc = mpn

            # Duplicate detection
            mpn_key = mpn.upper()
            if mpn_key in seen_mpns:
                duplicate_count += 1
            else:
                seen_mpns.add(mpn_key)

            items.append(EnrichmentRequest(mfg_part_num=mpn, part_desc=desc, raw_manuf=manuf or None))

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse catalog dataset: {str(e)}")

    if not items:
        raise HTTPException(status_code=400, detail="No valid catalog records found in uploaded file")

    batch.total_items = len(items)
    batch.status = "processing"
    await db.commit()

    # Enqueue background chunked worker
    enqueue_batch_job(batch_id, items)

    return {
        "batch_id": batch_id,
        "filename": filename,
        "total_records_queued": len(items),
        "unique_mpns": len(seen_mpns),
        "duplicates_detected": duplicate_count,
        "malformed_rows_skipped": malformed_count,
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
async def get_batch_results(
    batch_id: int,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Retrieve processed results array for a batch job with pagination."""
    results = BATCH_RESULTS_CACHE.get(batch_id, [])
    paginated = results[offset : offset + limit]
    return {
        "batch_id": batch_id,
        "total_results": len(results),
        "limit": limit,
        "offset": offset,
        "items": paginated,
    }


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


@router.post("/api/batches/{batch_id}/cancel")
async def cancel_batch_job(
    batch_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Gracefully cancel an active batch catalog processing job."""
    query = select(BatchJob).where(BatchJob.id == batch_id)
    result = await db.execute(query)
    batch = result.scalar_one_or_none()

    if not batch:
        raise HTTPException(status_code=404, detail="Batch job not found")

    job_queue_manager.cancel_job(batch_id)
    batch.status = "cancelled"
    await db.commit()

    return {"batch_id": batch_id, "status": "cancelled", "message": "Batch cancellation request received"}


@router.get("/api/batches/{batch_id}/failures")
async def get_batch_failures(batch_id: int) -> dict[str, Any]:
    """Retrieve recorded failure diagnostics for a batch job."""
    failures = job_queue_manager.get_failures(batch_id)
    return {
        "batch_id": batch_id,
        "failure_count": len(failures),
        "failures": failures,
    }


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
        ground_truth_only=payload.ground_truth_only,
        db=db,
    )
    return report


@router.get("/api/benchmark/runs")
async def list_benchmark_runs(
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List all historical benchmark evaluation runs."""
    query = select(BenchmarkRun).order_by(desc(BenchmarkRun.created_at)).limit(limit)
    result = await db.execute(query)
    runs = result.scalars().all()
    return {
        "total_runs": len(runs),
        "runs": [
            {
                "id": r.id,
                "name": r.name,
                "dataset_path": r.dataset_path,
                "total_rows": r.total_rows,
                "exact_match_rate": r.exact_match_rate,
                "field_accuracy": r.field_accuracy,
                "category_accuracy": r.category_accuracy,
                "brand_accuracy": r.brand_accuracy,
                "mpn_accuracy": r.mpn_accuracy,
                "attribute_accuracy": r.attribute_accuracy,
                "schema_compliance": r.schema_compliance,
                "uom_compliance": r.uom_compliance,
                "fraction_compliance": r.fraction_compliance,
                "invoice_compliance": r.invoice_compliance,
                "predictions_hash": r.predictions_hash,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in runs
        ],
    }


@router.get("/api/benchmark/{run_id}")
async def get_benchmark_report(
    run_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve historical benchmark run report."""
    query = select(BenchmarkRun).where(BenchmarkRun.id == run_id)
    result = await db.execute(query)
    bench = result.scalar_one_or_none()

    if not bench:
        raise HTTPException(status_code=404, detail="Benchmark run not found")

    return bench.report_json


@router.get("/api/benchmark/{run_id}/errors")
async def get_benchmark_errors(
    run_id: int,
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve specific mismatch and rule violation errors recorded during a benchmark run."""
    query = (
        select(BenchmarkResult)
        .where(BenchmarkResult.benchmark_run_id == run_id)
        .order_by(BenchmarkResult.row_index)
    )
    result = await db.execute(query)
    records = result.scalars().all()

    all_errors: list[dict[str, Any]] = []
    for rec in records:
        if rec.errors_json:
            for err in rec.errors_json:
                all_errors.append(err)

    return {
        "run_id": run_id,
        "total_errors": len(all_errors),
        "errors": all_errors[:limit],
    }


@router.get("/api/benchmark/{run_id}/results")
async def get_benchmark_results(
    run_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve per-record evaluation results for a benchmark run."""
    query = (
        select(BenchmarkResult)
        .where(BenchmarkResult.benchmark_run_id == run_id)
        .order_by(BenchmarkResult.row_index)
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(query)
    records = result.scalars().all()

    return {
        "run_id": run_id,
        "total": len(records),
        "offset": offset,
        "limit": limit,
        "results": [
            {
                "row_index": r.row_index,
                "mpn": r.mpn,
                "is_exact_match": r.is_exact_match,
                "predicted_brand": r.predicted_brand,
                "predicted_category": r.predicted_category,
                "predicted_invoice": r.predicted_invoice,
                "expected_brand": r.expected_brand,
                "expected_category": r.expected_category,
                "expected_invoice": r.expected_invoice,
                "confidence": r.confidence,
                "source_mode": r.source_mode,
                "field_scores": r.field_scores_json,
                "errors": r.errors_json,
            }
            for r in records
        ],
    }


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
