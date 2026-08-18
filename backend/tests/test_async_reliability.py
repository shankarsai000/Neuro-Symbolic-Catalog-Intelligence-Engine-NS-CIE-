from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.ai.schemas import EnrichmentRequest, EnrichmentResponse, ExtractedAttributes
from app.db.database import async_session, init_db
from app.db.models import BatchJob
from app.worker.batch_worker import (
    BATCH_FAILURES_CACHE,
    BATCH_RESULTS_CACHE,
    job_queue_manager,
    process_batch_job,
    resume_interrupted_batch,
)
from main import app

client = TestClient(app)


@pytest.mark.asyncio
async def test_normal_batch_processing_completes():
    """Verify normal batch of valid items runs to completion with 'completed' status."""
    await init_db()
    async with async_session() as db:
        batch = BatchJob(name="Reliability Normal Batch", filename="catalog.csv", status="queued", total_items=3)
        db.add(batch)
        await db.commit()
        await db.refresh(batch)
        batch_id = batch.id

    items = [
        EnrichmentRequest(mfg_part_num="DW-1", part_desc="Dishwasher SS 120V", raw_manuf="Frigidaire"),
        EnrichmentRequest(mfg_part_num="DW-2", part_desc="Dishwasher Built-in 120V", raw_manuf="Frigidaire"),
        EnrichmentRequest(mfg_part_num="DW-3", part_desc="Commercial Dishwasher 240V", raw_manuf="Frigidaire"),
    ]

    await process_batch_job(batch_id, items)

    async with async_session() as db:
        q = select(BatchJob).where(BatchJob.id == batch_id)
        res = await db.execute(q)
        b = res.scalar_one()
        assert b.status == "completed"
        assert b.processed_items == 3
        assert b.high_confidence_count > 0


@pytest.mark.asyncio
async def test_batch_survives_single_item_failure():
    """Verify a single failing product does not abort the batch and sets 'partial' status."""
    await init_db()
    async with async_session() as db:
        batch = BatchJob(name="Single Failure Batch", filename="catalog.csv", status="queued", total_items=3)
        db.add(batch)
        await db.commit()
        await db.refresh(batch)
        batch_id = batch.id

    items = [
        EnrichmentRequest(mfg_part_num="GOOD-1", part_desc="Good Item 120V", raw_manuf="Frigidaire"),
        EnrichmentRequest(mfg_part_num="BAD-1", part_desc="Failing Item", raw_manuf="Frigidaire"),
        EnrichmentRequest(mfg_part_num="GOOD-2", part_desc="Good Item 240V", raw_manuf="Frigidaire"),
    ]

    with patch("app.worker.batch_worker.run_enrichment_pipeline") as mock_pipeline:
        async def side_effect(req, db, batch_job_id=None):
            if req.mfg_part_num == "BAD-1":
                raise ValueError("Simulated network timeout on manufacturer portal")
            return EnrichmentResponse(
                mfg_part_num=req.mfg_part_num,
                canonical_brand="FRIGIDAIRE®",
                raw_description=req.part_desc,
                invoice_desc="GOOD ITEM 120 V",
                source_mode="OFFLINE_HEURISTIC",
                confidence_score=0.95,
                attributes=ExtractedAttributes(brand="FRIGIDAIRE®", item_type="Dishwasher"),
                delivery_record_preview={"PART_NUMBER": req.mfg_part_num},
            )

        mock_pipeline.side_effect = side_effect
        await process_batch_job(batch_id, items)

    async with async_session() as db:
        q = select(BatchJob).where(BatchJob.id == batch_id)
        res = await db.execute(q)
        b = res.scalar_one()
        assert b.status == "partial"
        assert b.processed_items == 3
        assert b.high_confidence_count == 2

    failures = job_queue_manager.get_failures(batch_id)
    assert len(failures) == 1
    assert failures[0]["mfg_part_num"] == "BAD-1"
    assert "Simulated network timeout" in failures[0]["error"]


@pytest.mark.asyncio
async def test_retry_mechanism_with_backoff():
    """Verify transient failures trigger retry with exponential backoff and succeed if recovered."""
    await init_db()
    async with async_session() as db:
        batch = BatchJob(name="Retry Batch", filename="catalog.csv", status="queued", total_items=1)
        db.add(batch)
        await db.commit()
        await db.refresh(batch)
        batch_id = batch.id

    items = [EnrichmentRequest(mfg_part_num="RETRY-1", part_desc="Transient Item", raw_manuf="Frigidaire")]
    attempts = 0

    with patch("app.worker.batch_worker.run_enrichment_pipeline") as mock_pipeline:
        async def retry_side_effect(req, db, batch_job_id=None):
            nonlocal attempts
            attempts += 1
            if attempts < 2:
                raise ConnectionResetError("Transient socket disconnect")
            return EnrichmentResponse(
                mfg_part_num=req.mfg_part_num,
                canonical_brand="FRIGIDAIRE®",
                raw_description=req.part_desc,
                invoice_desc="RETRY ITEM 120 V",
                source_mode="OFFLINE_HEURISTIC",
                confidence_score=0.95,
                attributes=ExtractedAttributes(brand="FRIGIDAIRE®", item_type="Dishwasher"),
                delivery_record_preview={"PART_NUMBER": req.mfg_part_num},
            )

        mock_pipeline.side_effect = retry_side_effect
        await process_batch_job(batch_id, items)

    assert attempts == 2  # Failed once, succeeded on 2nd attempt
    async with async_session() as db:
        q = select(BatchJob).where(BatchJob.id == batch_id)
        res = await db.execute(q)
        b = res.scalar_one()
        assert b.status == "completed"
        assert b.processed_items == 1


def test_batch_cancellation_endpoint():
    """Verify batch cancellation API transitions status to 'cancelled'."""
    create_resp = client.post("/api/batches", json={"name": "Cancel Test Batch", "filename": "test.csv"})
    batch_id = create_resp.json()["batch_id"]

    cancel_resp = client.post(f"/api/batches/{batch_id}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"

    status_resp = client.get(f"/api/batches/{batch_id}")
    assert status_resp.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_worker_restart_and_resume_from_checkpoint():
    """Verify worker can restart and resume an interrupted batch from its exact checkpoint."""
    await init_db()
    async with async_session() as db:
        batch = BatchJob(
            name="Resume Checkpoint Batch",
            filename="catalog.csv",
            status="processing",
            total_items=4,
            processed_items=2,  # Already processed first 2 items
        )
        db.add(batch)
        await db.commit()
        await db.refresh(batch)
        batch_id = batch.id

    items = [
        EnrichmentRequest(mfg_part_num="ITEM-1", part_desc="Item 1", raw_manuf="Frigidaire"),
        EnrichmentRequest(mfg_part_num="ITEM-2", part_desc="Item 2", raw_manuf="Frigidaire"),
        EnrichmentRequest(mfg_part_num="ITEM-3", part_desc="Item 3", raw_manuf="Frigidaire"),
        EnrichmentRequest(mfg_part_num="ITEM-4", part_desc="Item 4", raw_manuf="Frigidaire"),
    ]

    processed_calls = []
    with patch("app.worker.batch_worker.run_enrichment_pipeline") as mock_pipeline:
        async def resume_side_effect(req, db, batch_job_id=None):
            processed_calls.append(req.mfg_part_num)
            return EnrichmentResponse(
                mfg_part_num=req.mfg_part_num,
                canonical_brand="FRIGIDAIRE®",
                raw_description=req.part_desc,
                invoice_desc="RESUMED ITEM",
                source_mode="OFFLINE_HEURISTIC",
                confidence_score=0.95,
                attributes=ExtractedAttributes(brand="FRIGIDAIRE®", item_type="Dishwasher"),
                delivery_record_preview={"PART_NUMBER": req.mfg_part_num},
            )

        mock_pipeline.side_effect = resume_side_effect
        await resume_interrupted_batch(batch_id, items)

    # Must only process ITEM-3 and ITEM-4 (start_index=2)
    assert processed_calls == ["ITEM-3", "ITEM-4"]

    async with async_session() as db:
        q = select(BatchJob).where(BatchJob.id == batch_id)
        res = await db.execute(q)
        b = res.scalar_one()
        assert b.status == "completed"
        assert b.processed_items == 4
