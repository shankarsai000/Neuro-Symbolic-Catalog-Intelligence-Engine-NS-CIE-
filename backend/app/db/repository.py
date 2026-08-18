from __future__ import annotations

import datetime
import logging
from typing import Any, Optional, Sequence
from sqlalchemy import delete, desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    AuditEvent,
    BatchJob,
    BenchmarkResult,
    BenchmarkRun,
    EnrichmentRun,
    ExtractedAttribute,
    Product,
    ReviewAction,
    ReviewQueue,
    SchemaValidationResult,
    Source,
    SourceEvidence,
    utc_now,
)

logger = logging.getLogger(__name__)


class ProductRepository:
    """Repository managing Product records and lifecycle."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, product_id: int) -> Optional[Product]:
        query = (
            select(Product)
            .where(Product.id == product_id)
            .options(selectinload(Product.enrichment_runs), selectinload(Product.reviews))
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_by_mpn_and_brand(
        self, mfg_part_num: str, canonical_brand: Optional[str] = None
    ) -> Optional[Product]:
        query = select(Product).where(Product.mfg_part_num == mfg_part_num)
        if canonical_brand:
            query = query.where(Product.canonical_brand == canonical_brand)
        result = await self.db.execute(query)
        return result.scalars().first()

    async def create(
        self,
        mfg_part_num: str,
        part_desc: str,
        raw_manuf: Optional[str] = None,
        canonical_brand: Optional[str] = None,
        status: str = "pending",
    ) -> Product:
        product = Product(
            mfg_part_num=mfg_part_num,
            part_desc=part_desc,
            raw_manuf=raw_manuf,
            canonical_brand=canonical_brand,
            status=status,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.db.add(product)
        await self.db.flush()
        return product

    async def get_or_create(
        self,
        mfg_part_num: str,
        part_desc: str,
        raw_manuf: Optional[str] = None,
        canonical_brand: Optional[str] = None,
    ) -> Product:
        existing = await self.get_by_mpn_and_brand(mfg_part_num, canonical_brand)
        if existing:
            return existing
        return await self.create(mfg_part_num, part_desc, raw_manuf, canonical_brand)

    async def update_status(self, product_id: int, status: str) -> Optional[Product]:
        product = await self.get_by_id(product_id)
        if product:
            product.status = status
            product.updated_at = utc_now()
            await self.db.flush()
        return product

    async def list_products(
        self, limit: int = 100, offset: int = 0, status: Optional[str] = None
    ) -> Sequence[Product]:
        query = select(Product).order_by(desc(Product.created_at)).offset(offset).limit(limit)
        if status:
            query = query.where(Product.status == status)
        result = await self.db.execute(query)
        return result.scalars().all()


class EnrichmentRepository:
    """Repository managing EnrichmentRun and ExtractedAttribute entities."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_run(
        self,
        product_id: int,
        source_mode: str,
        confidence_score: float,
        provenance_score: float,
        lov_score: float,
        rule_score: float,
        invoice_desc: str,
        mobile_desc: str,
        product_title: str,
        long_desc: str,
        short_desc: Optional[str] = None,
        model_used: Optional[str] = None,
        batch_job_id: Optional[int] = None,
        execution_time_ms: float = 0.0,
        status: str = "completed",
    ) -> EnrichmentRun:
        run = EnrichmentRun(
            product_id=product_id,
            batch_job_id=batch_job_id,
            source_mode=source_mode,
            model_used=model_used,
            confidence_score=confidence_score,
            provenance_score=provenance_score,
            lov_score=lov_score,
            rule_score=rule_score,
            invoice_desc=invoice_desc,
            mobile_desc=mobile_desc,
            product_title=product_title,
            long_desc=long_desc,
            short_desc=short_desc,
            status=status,
            execution_time_ms=execution_time_ms,
            created_at=utc_now(),
        )
        self.db.add(run)
        await self.db.flush()
        return run

    async def add_attribute(
        self,
        enrichment_run_id: int,
        label: str,
        value: str,
        uom: Optional[str] = None,
        source_url: Optional[str] = None,
        source_type: str = "distributor_feed",
        evidence_text: Optional[str] = None,
        confidence: float = 1.0,
        is_lov_validated: bool = True,
    ) -> ExtractedAttribute:
        attr = ExtractedAttribute(
            enrichment_run_id=enrichment_run_id,
            attribute_label=label,
            attribute_value=value,
            attribute_uom=uom,
            source_url=source_url,
            source_type=source_type,
            evidence_text=evidence_text,
            confidence=confidence,
            is_lov_validated=is_lov_validated,
        )
        self.db.add(attr)
        await self.db.flush()
        return attr

    async def get_latest_for_product(self, product_id: int) -> Optional[EnrichmentRun]:
        query = (
            select(EnrichmentRun)
            .where(EnrichmentRun.product_id == product_id)
            .order_by(desc(EnrichmentRun.created_at))
            .options(selectinload(EnrichmentRun.attributes))
        )
        result = await self.db.execute(query)
        return result.scalars().first()


class SourceRepository:
    """Repository managing scraped/cached Manufacturer Sources and Evidences."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_source(self, brand: str, mpn: str) -> Optional[Source]:
        query = (
            select(Source)
            .where(Source.brand == brand, Source.mpn == mpn)
            .options(selectinload(Source.evidences))
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def save_source(
        self,
        brand: str,
        mpn: str,
        domain: str,
        source_url: str,
        raw_text: str,
        content_hash: str,
        source_type: str = "html",
        http_status: int = 200,
        parsed_evidence: Optional[dict[str, Any]] = None,
    ) -> Source:
        existing = await self.get_source(brand, mpn)
        if existing:
            existing.domain = domain
            existing.source_url = source_url
            existing.raw_text = raw_text
            existing.content_hash = content_hash
            existing.source_type = source_type
            existing.http_status = http_status
            existing.parsed_evidence_json = parsed_evidence or {}
            existing.retrieved_at = utc_now()
            await self.db.flush()
            return existing

        source = Source(
            brand=brand,
            mpn=mpn,
            domain=domain,
            source_url=source_url,
            raw_text=raw_text,
            content_hash=content_hash,
            source_type=source_type,
            http_status=http_status,
            parsed_evidence_json=parsed_evidence or {},
            retrieved_at=utc_now(),
        )
        self.db.add(source)
        await self.db.flush()
        return source

    async def add_evidence(
        self,
        source_id: int,
        spec_key: str,
        raw_snippet: str,
        extracted_value: str,
        confidence: float = 1.0,
    ) -> SourceEvidence:
        ev = SourceEvidence(
            source_id=source_id,
            spec_key=spec_key,
            raw_snippet=raw_snippet,
            extracted_value=extracted_value,
            confidence=confidence,
        )
        self.db.add(ev)
        await self.db.flush()
        return ev


class ReviewQueueRepository:
    """Repository managing Human-In-The-Loop (HITL) Review Queue and Audit Actions."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def enqueue(
        self,
        product_id: int,
        field_name: str,
        reason: str,
        original_value: Optional[str] = None,
        suggested_value: Optional[str] = None,
        current_value: Optional[str] = None,
        confidence: float = 0.0,
        enrichment_run_id: Optional[int] = None,
        batch_job_id: Optional[int] = None,
    ) -> ReviewQueue:
        review = ReviewQueue(
            product_id=product_id,
            enrichment_run_id=enrichment_run_id,
            batch_job_id=batch_job_id,
            field_name=field_name,
            original_value=original_value,
            suggested_value=suggested_value,
            current_value=current_value or suggested_value or original_value,
            reason=reason,
            confidence=confidence,
            status="PENDING",
            created_at=utc_now(),
        )
        self.db.add(review)
        await self.db.flush()
        return review

    async def get_by_id(self, review_id: int) -> Optional[ReviewQueue]:
        query = (
            select(ReviewQueue)
            .where(ReviewQueue.id == review_id)
            .options(selectinload(ReviewQueue.actions), selectinload(ReviewQueue.product))
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_pending(self, limit: int = 50, offset: int = 0) -> Sequence[ReviewQueue]:
        query = (
            select(ReviewQueue)
            .where(ReviewQueue.status == "PENDING")
            .order_by(ReviewQueue.confidence.asc(), desc(ReviewQueue.created_at))
            .offset(offset)
            .limit(limit)
            .options(selectinload(ReviewQueue.product))
        )
        result = await self.db.execute(query)
        return result.scalars().all()

    async def resolve_review(
        self,
        review_id: int,
        action_type: str,  # APPROVE, REJECT, EDIT
        new_value: Optional[str] = None,
        user_notes: Optional[str] = None,
    ) -> Optional[ReviewQueue]:
        review = await self.get_by_id(review_id)
        if not review:
            return None

        prev_val = review.current_value
        review.status = action_type.upper()
        if new_value is not None:
            review.current_value = new_value
        review.resolved_at = utc_now()

        action = ReviewAction(
            review_id=review.id,
            action_type=action_type.upper(),
            previous_value=prev_val,
            new_value=new_value or review.current_value,
            user_notes=user_notes,
            timestamp=utc_now(),
        )
        self.db.add(action)
        await self.db.flush()
        return review


class BatchJobRepository:
    """Repository managing Batch catalog enrichment jobs."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_job(self, name: str, filename: str, total_items: int = 0) -> BatchJob:
        job = BatchJob(
            name=name,
            filename=filename,
            total_items=total_items,
            processed_items=0,
            status="pending",
            created_at=utc_now(),
        )
        self.db.add(job)
        await self.db.flush()
        return job

    async def get_by_id(self, job_id: int) -> Optional[BatchJob]:
        query = select(BatchJob).where(BatchJob.id == job_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def update_progress(
        self,
        job_id: int,
        processed: int,
        high_conf: int,
        review_needed: int,
        avg_conf: float,
        status: str = "processing",
    ) -> Optional[BatchJob]:
        job = await self.get_by_id(job_id)
        if job:
            job.processed_items = processed
            job.high_confidence_count = high_conf
            job.review_needed_count = review_needed
            job.average_confidence = avg_conf
            job.status = status
            if status == "completed":
                job.completed_at = utc_now()
            await self.db.flush()
        return job


class AuditEventRepository:
    """Repository recording structured audit trail events."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def log_event(
        self,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> AuditEvent:
        event = AuditEvent(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=str(entity_id),
            payload_json=payload or {},
            timestamp=utc_now(),
        )
        self.db.add(event)
        await self.db.flush()
        return event

    async def list_events(
        self,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        limit: int = 100,
    ) -> Sequence[AuditEvent]:
        query = select(AuditEvent).order_by(desc(AuditEvent.timestamp)).limit(limit)
        if entity_type:
            query = query.where(AuditEvent.entity_type == entity_type)
        if entity_id:
            query = query.where(AuditEvent.entity_id == str(entity_id))
        result = await self.db.execute(query)
        return result.scalars().all()


class BenchmarkRepository:
    """Repository managing Ground-Truth Benchmark runs and evaluation metrics."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_run(
        self,
        name: str,
        dataset_path: str,
        total_rows: int,
        exact_match_rate: float,
        field_accuracy: float,
        category_accuracy: float,
        schema_compliance: float,
        uom_compliance: float,
        fraction_compliance: float,
        invoice_compliance: float,
        report_json: Optional[dict[str, Any]] = None,
        status: str = "completed",
    ) -> BenchmarkRun:
        run = BenchmarkRun(
            name=name,
            dataset_path=dataset_path,
            total_rows=total_rows,
            exact_match_rate=exact_match_rate,
            field_accuracy=field_accuracy,
            category_accuracy=category_accuracy,
            schema_compliance=schema_compliance,
            uom_compliance=uom_compliance,
            fraction_compliance=fraction_compliance,
            invoice_compliance=invoice_compliance,
            report_json=report_json or {},
            status=status,
            created_at=utc_now(),
        )
        self.db.add(run)
        await self.db.flush()
        return run

    async def add_result(
        self,
        benchmark_run_id: int,
        row_index: int,
        mpn: str,
        is_exact_match: bool,
        field_scores: Optional[dict[str, Any]] = None,
        errors: Optional[list[Any]] = None,
    ) -> BenchmarkResult:
        result = BenchmarkResult(
            benchmark_run_id=benchmark_run_id,
            row_index=row_index,
            mpn=mpn,
            is_exact_match=is_exact_match,
            field_scores_json=field_scores or {},
            errors_json=errors or [],
        )
        self.db.add(result)
        await self.db.flush()
        return result

    async def get_latest_run(self) -> Optional[BenchmarkRun]:
        query = (
            select(BenchmarkRun)
            .order_by(desc(BenchmarkRun.created_at))
            .options(selectinload(BenchmarkRun.results))
        )
        result = await self.db.execute(query)
        return result.scalars().first()
