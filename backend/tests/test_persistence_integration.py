from __future__ import annotations

import datetime
import pytest
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import (
    async_session,
    check_db_connectivity,
    init_db,
    transactional_session,
)
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
    Source,
    SourceEvidence,
)
from app.db.repository import (
    AuditEventRepository,
    BatchJobRepository,
    BenchmarkRepository,
    EnrichmentRepository,
    ProductRepository,
    ReviewQueueRepository,
    SourceRepository,
)


@pytest.mark.asyncio
async def test_database_connectivity_and_initialization():
    """Verify database connectivity check and schema initialization."""
    is_connected = await check_db_connectivity(max_retries=2, retry_delay=0.1)
    assert is_connected is True
    await init_db()


@pytest.mark.asyncio
async def test_product_crud_lifecycle():
    """Verify complete lifecycle of Product records."""
    unique_mpn = f"TST-{uuid.uuid4().hex[:8].upper()}"
    async with async_session() as db:
        repo = ProductRepository(db)

        # 1. Create
        product = await repo.create(
            mfg_part_num=unique_mpn,
            part_desc="Test industrial valve 120 V 1/2 in",
            raw_manuf="Test Corp LLC",
            canonical_brand="TEST CORP",
            status="pending",
        )
        await db.commit()
        product_id = product.id
        assert product_id > 0
        assert product.mfg_part_num == unique_mpn
        assert product.canonical_brand == "TEST CORP"

    async with async_session() as db:
        repo = ProductRepository(db)

        # 2. Read
        fetched = await repo.get_by_id(product_id)
        assert fetched is not None
        assert fetched.mfg_part_num == unique_mpn

        # 3. Update status
        updated = await repo.update_status(product_id, "enriched")
        await db.commit()
        assert updated is not None
        assert updated.status == "enriched"

        # 4. Query by MPN & Brand
        by_mpn = await repo.get_by_mpn_and_brand(unique_mpn, "TEST CORP")
        assert by_mpn is not None
        assert by_mpn.id == product_id


@pytest.mark.asyncio
async def test_enrichment_run_and_extracted_attributes_persistence():
    """Verify EnrichmentRun with ExtractedAttribute children and mathematical scores."""
    async with async_session() as db:
        prod_repo = ProductRepository(db)
        enrich_repo = EnrichmentRepository(db)

        prod = await prod_repo.create(
            mfg_part_num="ENR-200-VALVE",
            part_desc="Stainless steel ball valve 3/4 in",
            canonical_brand="VALVE CORP",
        )
        await db.commit()

        run = await enrich_repo.create_run(
            product_id=prod.id,
            source_mode="LIVE_NIM",
            confidence_score=0.985,
            provenance_score=1.0,
            lov_score=1.0,
            rule_score=0.95,
            invoice_desc="VALVE BALL SST 3/4 IN",
            mobile_desc="VALVE CORP, Valve, Series 200, ENR-200-VALVE",
            product_title="VALVE CORP® Series 200 ENR-200-VALVE Ball Valve",
            long_desc="Heavy duty stainless steel ball valve with 3/4 in threaded connections.",
            model_used="nvidia/nemotron-3.5-lightning-30b-a3b",
            execution_time_ms=145.2,
        )

        # Add field-level extracted attributes with provenance
        await enrich_repo.add_attribute(
            enrichment_run_id=run.id,
            label="Material",
            value="Stainless Steel",
            source_url="https://valvecorp.com/spec/200",
            source_type="manufacturer_official",
            evidence_text="Body Material: 316 Stainless Steel",
            confidence=1.0,
            is_lov_validated=True,
        )

        await enrich_repo.add_attribute(
            enrichment_run_id=run.id,
            label="Inlet Size",
            value="3/4",
            uom="in",
            source_type="distributor_feed",
            confidence=0.95,
            is_lov_validated=True,
        )
        await db.commit()

    async with async_session() as db:
        enrich_repo = EnrichmentRepository(db)
        latest_run = await enrich_repo.get_latest_for_product(prod.id)
        assert latest_run is not None
        assert latest_run.confidence_score == 0.985
        assert latest_run.invoice_desc == "VALVE BALL SST 3/4 IN"
        assert len(latest_run.attributes) == 2
        labels = [a.attribute_label for a in latest_run.attributes]
        assert "Material" in labels
        assert "Inlet Size" in labels


@pytest.mark.asyncio
async def test_source_and_evidence_persistence():
    """Verify Source official document caching and granular spec evidence."""
    unique_mpn = f"HOM250-{uuid.uuid4().hex[:6].upper()}"
    async with async_session() as db:
        repo = SourceRepository(db)
        source = await repo.save_source(
            brand="SCHNEIDER ELECTRIC",
            mpn=unique_mpn,
            domain="se.com",
            source_url=f"https://www.se.com/us/en/product/{unique_mpn}/",
            raw_text="Homeline Circuit Breaker 2-Pole 50 A 120/240 V",
            content_hash="a1b2c3d4e5f67890",
            source_type="html",
            http_status=200,
            parsed_evidence={"voltage": "120/240 V", "amperage": "50 A"},
        )
        await db.commit()

        await repo.add_evidence(
            source_id=source.id,
            spec_key="voltage",
            raw_snippet="Rated operational voltage: 120/240 V AC",
            extracted_value="120/240 V",
            confidence=1.0,
        )
        await db.commit()

    async with async_session() as db:
        repo = SourceRepository(db)
        cached = await repo.get_source("SCHNEIDER ELECTRIC", unique_mpn)
        assert cached is not None
        assert cached.domain == "se.com"
        assert cached.parsed_evidence_json.get("amperage") == "50 A"
        assert len(cached.evidences) == 1
        assert cached.evidences[0].spec_key == "voltage"


@pytest.mark.asyncio
async def test_review_queue_workflow_and_action_history():
    """Verify Human-In-The-Loop review enqueuing, resolution, and action history."""
    async with async_session() as db:
        prod_repo = ProductRepository(db)
        review_repo = ReviewQueueRepository(db)

        prod = await prod_repo.create(
            mfg_part_num="HITL-999-ITEM",
            part_desc="Ambiguous breaker part 20a",
            canonical_brand="SQUARE D",
        )
        await db.commit()

        item = await review_repo.enqueue(
            product_id=prod.id,
            field_name="voltage",
            reason="Low confidence extraction (0.65)",
            original_value="20a",
            suggested_value="120 V",
            confidence=0.65,
        )
        await db.commit()
        review_id = item.id

    async with async_session() as db:
        review_repo = ReviewQueueRepository(db)
        pending = await review_repo.list_pending()
        pending_ids = [p.id for p in pending]
        assert review_id in pending_ids

        # Resolve review with edit
        resolved = await review_repo.resolve_review(
            review_id=review_id,
            action_type="EDIT",
            new_value="240 V",
            user_notes="Corrected voltage based on technical sheet.",
        )
        await db.commit()
        assert resolved is not None
        assert resolved.status == "EDIT"
        assert resolved.current_value == "240 V"

    async with async_session() as db:
        review_repo = ReviewQueueRepository(db)
        refetched = await review_repo.get_by_id(review_id)
        assert refetched is not None
        assert refetched.status == "EDIT"
        assert len(refetched.actions) == 1
        assert refetched.actions[0].action_type == "EDIT"
        assert refetched.actions[0].new_value == "240 V"
        assert refetched.actions[0].user_notes == "Corrected voltage based on technical sheet."


@pytest.mark.asyncio
async def test_batch_job_progress_tracking():
    """Verify BatchJob persistence and progress updates."""
    async with async_session() as db:
        repo = BatchJobRepository(db)
        job = await repo.create_job(name="Test Catalog Run", filename="catalog.csv", total_items=100)
        await db.commit()
        job_id = job.id

    async with async_session() as db:
        repo = BatchJobRepository(db)
        updated = await repo.update_progress(
            job_id=job_id,
            processed=50,
            high_conf=45,
            review_needed=5,
            avg_conf=0.942,
            status="processing",
        )
        await db.commit()
        assert updated is not None
        assert updated.processed_items == 50
        assert updated.average_confidence == 0.942

        completed = await repo.update_progress(
            job_id=job_id,
            processed=100,
            high_conf=92,
            review_needed=8,
            avg_conf=0.958,
            status="completed",
        )
        await db.commit()
        assert completed is not None
        assert completed.status == "completed"
        assert completed.completed_at is not None


@pytest.mark.asyncio
async def test_audit_event_logging():
    """Verify AuditEvent recording and filtering."""
    async with async_session() as db:
        repo = AuditEventRepository(db)
        event = await repo.log_event(
            event_type="ENRICHMENT_COMPLETED",
            entity_type="product",
            entity_id="12345",
            payload={"confidence": 0.99, "source_mode": "LIVE_NIM"},
        )
        await db.commit()
        assert event.id > 0

    async with async_session() as db:
        repo = AuditEventRepository(db)
        events = await repo.list_events(entity_type="product", entity_id="12345")
        assert len(events) >= 1
        assert events[0].event_type == "ENRICHMENT_COMPLETED"
        assert events[0].payload_json.get("source_mode") == "LIVE_NIM"


@pytest.mark.asyncio
async def test_benchmark_run_and_results_persistence():
    """Verify ground-truth BenchmarkRun and BenchmarkResults storage."""
    async with async_session() as db:
        repo = BenchmarkRepository(db)
        run = await repo.create_run(
            name="Unilog 200 Evaluation",
            dataset_path="data/Unihack_Sample.csv",
            total_rows=200,
            exact_match_rate=98.5,
            field_accuracy=99.1,
            category_accuracy=100.0,
            schema_compliance=100.0,
            uom_compliance=100.0,
            fraction_compliance=100.0,
            invoice_compliance=100.0,
            report_json={"passed": 197, "failed": 3},
        )
        await db.commit()

        await repo.add_result(
            benchmark_run_id=run.id,
            row_index=0,
            mpn="PDSH4816AF",
            is_exact_match=True,
            field_scores={"brand": 1.0, "invoice_desc": 1.0},
        )
        await db.commit()

    async with async_session() as db:
        repo = BenchmarkRepository(db)
        latest = await repo.get_latest_run()
        assert latest is not None
        assert latest.name == "Unilog 200 Evaluation"
        assert latest.exact_match_rate == 98.5
        assert len(latest.results) >= 1
        assert latest.results[0].mpn == "PDSH4816AF"


@pytest.mark.asyncio
async def test_transaction_rollback_safety():
    """Verify that failed transactions roll back changes cleanly."""
    product_mpn = "ROLLBACK-TEST-MPN"
    
    try:
        async with transactional_session() as db:
            prod_repo = ProductRepository(db)
            await prod_repo.create(
                mfg_part_num=product_mpn,
                part_desc="Should be rolled back",
            )
            # Deliberately raise exception inside transaction
            raise RuntimeError("Simulated failure to test rollback")
    except RuntimeError:
        pass

    async with async_session() as db:
        repo = ProductRepository(db)
        existing = await repo.get_by_mpn_and_brand(product_mpn)
        assert existing is None, "Product should have been rolled back"
