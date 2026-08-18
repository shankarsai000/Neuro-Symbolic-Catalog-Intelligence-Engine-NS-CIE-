from __future__ import annotations

import asyncio
import json
import logging
import os
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

# Redis URL and fallback state
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Active in-memory state tracking
ACTIVE_BATCH_TASKS: dict[int, asyncio.Task] = {}
BATCH_RESULTS_CACHE: dict[int, list[dict[str, Any]]] = {}
BATCH_FAILURES_CACHE: dict[int, list[dict[str, Any]]] = {}
BATCH_CANCEL_FLAGS: set[int] = set()

# Retry settings
MAX_ITEM_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 0.05
BATCH_CHUNK_SIZE = 25


class JobQueueManager:
    """Manages Redis and in-memory job queues, checkpoints, cancellation, and failure diagnostics."""

    def __init__(self, redis_url: str = REDIS_URL):
        self.redis_url = redis_url
        self._redis_client = None
        self._is_redis_available = False

    @property
    def is_redis_available(self) -> bool:
        return self._is_redis_available

    async def initialize(self) -> None:
        """Attempt connection to Redis with graceful fallback to in-memory store."""
        try:
            import redis.asyncio as aioredis
            self._redis_client = aioredis.from_url(self.redis_url, decode_responses=True)
            await self._redis_client.ping()
            self._is_redis_available = True
            logger.info("Connected successfully to Redis job queue.")
        except Exception as e:
            self._is_redis_available = False
            logger.info(f"Redis unavailable ({e}); using resilient in-memory job manager.")

    def cancel_job(self, batch_id: int) -> None:
        """Signal job cancellation."""
        BATCH_CANCEL_FLAGS.add(batch_id)
        task = ACTIVE_BATCH_TASKS.get(batch_id)
        if task and not task.done():
            task.cancel()

    def is_cancelled(self, batch_id: int) -> bool:
        return batch_id in BATCH_CANCEL_FLAGS

    def record_failure(self, batch_id: int, mpn: str, error: str, retry_count: int) -> None:
        """Record diagnostic failure details for an item."""
        failures = BATCH_FAILURES_CACHE.setdefault(batch_id, [])
        failures.append({
            "mfg_part_num": mpn,
            "error": error,
            "retries_attempted": retry_count,
            "timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        })

    def get_failures(self, batch_id: int) -> list[dict[str, Any]]:
        return BATCH_FAILURES_CACHE.get(batch_id, [])


job_queue_manager = JobQueueManager()


async def process_batch_job(
    batch_id: int,
    items: list[EnrichmentRequest],
    start_index: int = 0,
    chunk_size: int = BATCH_CHUNK_SIZE,
) -> None:
    """Execute batch job with retry backoff, checkpointing, cancellation, and partial status support."""
    async with async_session() as db:
        query = select(BatchJob).where(BatchJob.id == batch_id)
        result = await db.execute(query)
        batch = result.scalar_one_or_none()

        if not batch:
            logger.error(f"Batch job {batch_id} not found in database")
            return

        batch.status = "processing"
        batch.total_items = len(items)
        if start_index == 0:
            batch.processed_items = 0
            batch.high_confidence_count = 0
            batch.review_needed_count = 0
            batch.average_confidence = 0.0
        await db.commit()

    processed = start_index
    high_conf = 0
    review_needed = 0
    total_conf = 0.0
    failed_items_count = 0
    batch_results: list[dict[str, Any]] = BATCH_RESULTS_CACHE.get(batch_id, [])

    for i in range(start_index, len(items), chunk_size):
        # Check cancellation
        if job_queue_manager.is_cancelled(batch_id):
            logger.info(f"Batch #{batch_id} was cancelled by user request.")
            async with async_session() as db:
                q = select(BatchJob).where(BatchJob.id == batch_id)
                res = await db.execute(q)
                b = res.scalar_one_or_none()
                if b:
                    b.status = "cancelled"
                    b.processed_items = processed
                    await db.commit()
            return

        chunk = items[i : i + chunk_size]

        for item in chunk:
            # Check cancellation per item
            if job_queue_manager.is_cancelled(batch_id):
                break

            success = False
            last_error = ""

            # Retry loop with exponential backoff
            for attempt in range(1, MAX_ITEM_RETRIES + 1):
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
                    success = True
                    break
                except Exception as e:
                    last_error = str(e)
                    backoff = INITIAL_BACKOFF_SECONDS * (2 ** (attempt - 1))
                    logger.warning(
                        f"Item {item.mfg_part_num} in batch #{batch_id} failed attempt {attempt}/{MAX_ITEM_RETRIES}: {e}. "
                        f"Retrying in {backoff:.2f}s..."
                    )
                    await asyncio.sleep(backoff)

            if not success:
                failed_items_count += 1
                job_queue_manager.record_failure(
                    batch_id=batch_id,
                    mpn=item.mfg_part_num,
                    error=last_error or "Max retries exceeded",
                    retry_count=MAX_ITEM_RETRIES,
                )
                # Resilient fallback record so remaining records complete
                batch_results.append({
                    "PART_NUMBER": item.mfg_part_num,
                    "Mfg_Part_Num": item.mfg_part_num,
                    "Part_Desc": item.part_desc,
                    "MANUFACTURER_NAME": item.raw_manuf or "UNASSIGNED",
                    "BRAND_NAME": item.raw_manuf or "UNASSIGNED",
                    "INVOICE_DESC": item.part_desc[:40].upper(),
                    "MOBILE_DESC": item.part_desc[:78],
                    "Product Name": item.part_desc[:80],
                    "Actual Image (Yes/No)": "No",
                })

            processed += 1

        # Checkpoint to database after every chunk
        async with async_session() as db:
            q = select(BatchJob).where(BatchJob.id == batch_id)
            res = await db.execute(q)
            b = res.scalar_one_or_none()
            if b and b.status != "cancelled":
                b.processed_items = processed
                b.high_confidence_count = high_conf
                b.review_needed_count = review_needed
                b.average_confidence = round(total_conf / max(processed - failed_items_count, 1), 3)
                await db.commit()

        BATCH_RESULTS_CACHE[batch_id] = batch_results
        await asyncio.sleep(0.01)

    # Check final cancellation status
    if job_queue_manager.is_cancelled(batch_id):
        final_status = "cancelled"
    elif failed_items_count == 0:
        final_status = "completed"
    elif failed_items_count == len(items):
        final_status = "failed"
    else:
        final_status = "partial"

    async with async_session() as db:
        q = select(BatchJob).where(BatchJob.id == batch_id)
        res = await db.execute(q)
        b = res.scalar_one_or_none()
        if b:
            b.status = final_status
            b.processed_items = processed
            b.high_confidence_count = high_conf
            b.review_needed_count = review_needed
            b.average_confidence = round(total_conf / max(processed - failed_items_count, 1), 3)
            await db.commit()

    BATCH_RESULTS_CACHE[batch_id] = batch_results
    logger.info(
        f"Batch #{batch_id} finalized with status '{final_status}': {processed}/{len(items)} processed, "
        f"{high_conf} high confidence, {review_needed} review needed, {failed_items_count} failures."
    )


def enqueue_batch_job(batch_id: int, items: list[EnrichmentRequest], start_index: int = 0) -> None:
    """Enqueue an async background worker task for batch catalog enrichment."""
    task = asyncio.create_task(process_batch_job(batch_id, items, start_index=start_index))
    ACTIVE_BATCH_TASKS[batch_id] = task


async def resume_interrupted_batch(batch_id: int, items: list[EnrichmentRequest]) -> None:
    """Resume an interrupted or queued batch from its last saved database checkpoint."""
    async with async_session() as db:
        q = select(BatchJob).where(BatchJob.id == batch_id)
        res = await db.execute(q)
        b = res.scalar_one_or_none()
        if not b:
            return
        start_idx = b.processed_items or 0

    if start_idx < len(items):
        logger.info(f"Resuming batch #{batch_id} from checkpoint item {start_idx}/{len(items)}")
        await process_batch_job(batch_id, items, start_index=start_idx)


async def run_worker_daemon() -> None:
    """Continuous background worker daemon loop for standalone worker execution."""
    logger.info("Initializing NS-CIE Background Batch Worker Daemon...")
    await init_db()
    await job_queue_manager.initialize()
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
