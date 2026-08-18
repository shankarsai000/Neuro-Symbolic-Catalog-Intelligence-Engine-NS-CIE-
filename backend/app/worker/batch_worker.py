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

# Active background batch tasks and in-memory results cache
ACTIVE_BATCH_TASKS: dict[int, asyncio.Task] = {}
BATCH_RESULTS_CACHE: dict[int, list[dict[str, Any]]] = {}

# Maximum items per worker chunk to prevent unbounded memory usage
BATCH_CHUNK_SIZE = 25


async def process_batch_job(
    batch_id: int,
    items: list[EnrichmentRequest],
    chunk_size: int = BATCH_CHUNK_SIZE,
) -> None:
    """Asynchronous background worker function to process a batch of catalog items in bounded chunks."""
    async with async_session() as db:
        query = select(BatchJob).where(BatchJob.id == batch_id)
        result = await db.execute(query)
        batch = result.scalar_one_or_none()

        if not batch:
            logger.error(f"Batch job {batch_id} not found")
            return

        batch.status = "processing"
        batch.total_items = len(items)
        batch.processed_items = 0
        await db.commit()

    processed = 0
    high_conf = 0
    review_needed = 0
    total_conf = 0.0
    failed_items_count = 0
    batch_results: list[dict[str, Any]] = []

    # Process items in bounded chunks
    for i in range(0, len(items), chunk_size):
        chunk = items[i : i + chunk_size]
        chunk_tasks = []

        for item in chunk:
            async def _process_single(single_item: EnrichmentRequest):
                async with async_session() as db:
                    res = await run_enrichment_pipeline(single_item, db=db, batch_job_id=batch_id)
                    await db.commit()
                    return res

            chunk_tasks.append(_process_single(item))

        # Execute chunk with exception isolation
        chunk_responses = await asyncio.gather(*chunk_tasks, return_exceptions=True)

        for item, resp in zip(chunk, chunk_responses):
            processed += 1
            if isinstance(resp, Exception):
                logger.error(f"Error enriching item {item.mfg_part_num} in batch {batch_id}: {resp}")
                failed_items_count += 1
                # Create a minimal safe record for partial completion resilience
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
            else:
                conf = resp.confidence_score
                total_conf += conf
                if conf >= 0.90:
                    high_conf += 1
                else:
                    review_needed += 1

                batch_results.append(resp.delivery_record_preview or {})

        # Synchronize live progress to database after every chunk
        async with async_session() as db:
            q = select(BatchJob).where(BatchJob.id == batch_id)
            res = await db.execute(q)
            b = res.scalar_one_or_none()
            if b:
                b.processed_items = processed
                b.high_confidence_count = high_conf
                b.review_needed_count = review_needed
                b.average_confidence = round(total_conf / max(processed - failed_items_count, 1), 3)
                await db.commit()

        # Yield to event loop to allow other requests to process smoothly
        await asyncio.sleep(0.01)

    # Finalize batch status
    final_status = "completed" if failed_items_count == 0 else "completed_with_errors"
    if failed_items_count == len(items):
        final_status = "failed"

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
        f"Batch job #{batch_id} finalized with status '{final_status}' ({processed}/{len(items)} processed, "
        f"{high_conf} high confidence, {review_needed} review needed, {failed_items_count} errors)."
    )


def enqueue_batch_job(batch_id: int, items: list[EnrichmentRequest]) -> None:
    """Enqueue an async background worker task for chunked batch catalog enrichment."""
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
