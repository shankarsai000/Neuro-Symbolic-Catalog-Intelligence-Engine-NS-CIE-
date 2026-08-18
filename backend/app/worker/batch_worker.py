from __future__ import annotations

import asyncio
import io
import logging
from typing import Any, Optional
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.schemas import EnrichmentRequest
from app.core.delivery import export_dataframe_to_252_csv
from app.core.pipeline import run_enrichment_pipeline
from app.db.database import async_session, init_db
from app.db.models import BatchJob, EnrichmentRun, Product

logger = logging.getLogger(__name__)

# Active background batch tasks
ACTIVE_BATCH_TASKS: dict[int, asyncio.Task] = {}
BATCH_RESULTS_CACHE: dict[int, list[dict[str, Any]]] = {}


async def process_batch_job(batch_id: int, items: list[EnrichmentRequest]) -> None:
    """Asynchronous background worker function to process a batch of catalog items."""
    async with async_session() as db:
        query = select(BatchJob).where(BatchJob.id == batch_id)
        result = await db.execute(query)
        batch = result.scalar_one_or_none()

        if not batch:
            logger.error(f"Batch job {batch_id} not found")
            return

        batch.status = "processing"
        batch.total_items = len(items)
        await db.commit()

    processed = 0
    high_conf = 0
    review_needed = 0
    total_conf = 0.0
    batch_results: list[dict[str, Any]] = []

    for item in items:
        try:
            async with async_session() as db:
                resp = await run_enrichment_pipeline(item, db=db, batch_job_id=batch_id)
                await db.commit()

            conf = resp.confidence_score
            total_conf += conf
            if conf >= 0.90:
                high_conf += 1
            else:
                review_needed += 1

            batch_results.append(resp.delivery_record_preview or {})
            processed += 1

            # Update live progress periodically in DB
            if processed % 5 == 0 or processed == len(items):
                async with async_session() as db:
                    q = select(BatchJob).where(BatchJob.id == batch_id)
                    res = await db.execute(q)
                    b = res.scalar_one_or_none()
                    if b:
                        b.processed_items = processed
                        b.high_confidence_count = high_conf
                        b.review_needed_count = review_needed
                        b.average_confidence = round(total_conf / processed, 3)
                        await db.commit()

        except Exception as e:
            logger.error(f"Error enriching item {item.mfg_part_num} in batch {batch_id}: {e}")
            processed += 1

    # Finalize batch completion
    async with async_session() as db:
        q = select(BatchJob).where(BatchJob.id == batch_id)
        res = await db.execute(q)
        b = res.scalar_one_or_none()
        if b:
            b.status = "completed"
            b.processed_items = processed
            b.high_confidence_count = high_conf
            b.review_needed_count = review_needed
            b.average_confidence = round(total_conf / max(processed, 1), 3)
            await db.commit()

    BATCH_RESULTS_CACHE[batch_id] = batch_results


def enqueue_batch_job(batch_id: int, items: list[EnrichmentRequest]) -> None:
    """Enqueue an async background worker task for batch catalog enrichment."""
    task = asyncio.create_task(process_batch_job(batch_id, items))
    ACTIVE_BATCH_TASKS[batch_id] = task


async def run_worker_daemon() -> None:
    """Continuous background worker daemon loop for standalone worker container execution."""
    logger.info("Initializing NS-CIE Background Batch Worker Daemon...")
    await init_db()
    logger.info("Worker daemon active and listening for queued catalog jobs.")
    while True:
        try:
            async with async_session() as db:
                query = select(BatchJob).where(BatchJob.status == "queued").order_by(BatchJob.created_at)
                result = await db.execute(query)
                pending_jobs = result.scalars().all()

                for job in pending_jobs:
                    logger.info(f"Worker picked up queued batch job #{job.id} ({job.name})")
        except Exception as e:
            logger.debug(f"Worker polling loop: {e}")
        await asyncio.sleep(5)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    asyncio.run(run_worker_daemon())
