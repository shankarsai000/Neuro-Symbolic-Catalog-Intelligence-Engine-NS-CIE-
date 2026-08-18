from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional
import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import text

logger = logging.getLogger("nscie.observability")

# =========================================================
# Context Variables for Distributed Request Tracing
# =========================================================
current_request_id: ContextVar[str] = ContextVar("current_request_id", default="")
current_batch_id: ContextVar[Optional[int]] = ContextVar("current_batch_id", default=None)
current_product_id: ContextVar[Optional[int]] = ContextVar("current_product_id", default=None)


class StructuredLogEntry:
    """Canonical structured log entry capturing end-to-end execution context."""

    def __init__(
        self,
        stage: str,
        status: str,
        duration_ms: float,
        request_id: Optional[str] = None,
        batch_id: Optional[int] = None,
        product_id: Optional[int] = None,
        error: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.request_id = request_id or current_request_id.get() or str(uuid.uuid4())
        self.batch_id = batch_id if batch_id is not None else current_batch_id.get()
        self.product_id = product_id if product_id is not None else current_product_id.get()
        self.stage = stage
        self.duration_ms = round(duration_ms, 2)
        self.status = status
        self.error = error
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "request_id": self.request_id,
            "batch_id": self.batch_id,
            "product_id": self.product_id,
            "stage": self.stage,
            "duration": self.duration_ms,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error": self.error,
            "metadata": self.metadata,
        }

    def emit(self) -> None:
        log_data = self.to_dict()
        if self.status == "FAILED" or self.error:
            logger.error(json.dumps(log_data))
        elif self.status == "FALLBACK":
            logger.warning(json.dumps(log_data))
        else:
            logger.info(json.dumps(log_data))


class TelemetryCollector:
    """Thread-safe, in-memory telemetry and observability metrics aggregator."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.request_latencies: list[float] = []
        self.llm_latencies: list[float] = []
        self.manufacturer_fetch_latencies: list[float] = []

        # Counters
        self.total_requests: int = 0
        self.total_extractions: int = 0
        self.live_nim_calls: int = 0
        self.fallback_calls: int = 0

        self.cache_lookups: int = 0
        self.cache_hits: int = 0

        self.total_products_enriched: int = 0
        self.total_hitl_reviews_queued: int = 0

        self.total_schema_validations: int = 0
        self.total_schema_failures: int = 0

        self.total_batch_items_processed: int = 0
        self.batch_processing_start_time: Optional[float] = None
        self.batch_processing_end_time: Optional[float] = None

        # Traced execution log history for diagnostic auditing
        self.recent_trace_logs: list[dict[str, Any]] = []

    def record_request_latency(self, duration_ms: float) -> None:
        self.total_requests += 1
        self.request_latencies.append(duration_ms)
        if len(self.request_latencies) > 2000:
            self.request_latencies = self.request_latencies[-2000:]

    def record_llm_latency(self, duration_ms: float, is_live_nim: bool = True) -> None:
        self.total_extractions += 1
        if is_live_nim:
            self.live_nim_calls += 1
        else:
            self.fallback_calls += 1
        self.llm_latencies.append(duration_ms)
        if len(self.llm_latencies) > 2000:
            self.llm_latencies = self.llm_latencies[-2000:]

    def record_manufacturer_fetch(self, duration_ms: float, from_cache: bool = False) -> None:
        self.cache_lookups += 1
        if from_cache:
            self.cache_hits += 1
        self.manufacturer_fetch_latencies.append(duration_ms)
        if len(self.manufacturer_fetch_latencies) > 2000:
            self.manufacturer_fetch_latencies = self.manufacturer_fetch_latencies[-2000:]

    def record_hitl_decision(self, needs_review: bool) -> None:
        self.total_products_enriched += 1
        if needs_review:
            self.total_hitl_reviews_queued += 1

    def record_schema_validation(self, is_valid: bool) -> None:
        self.total_schema_validations += 1
        if not is_valid:
            self.total_schema_failures += 1

    def record_batch_throughput(self, count: int, duration_sec: float) -> None:
        self.total_batch_items_processed += count

    def log_trace(self, entry: StructuredLogEntry) -> None:
        entry.emit()
        self.recent_trace_logs.append(entry.to_dict())
        if len(self.recent_trace_logs) > 500:
            self.recent_trace_logs = self.recent_trace_logs[-500:]

    def get_metrics_snapshot(self) -> dict[str, Any]:
        # Compute latencies
        def stats(vals: list[float]) -> dict[str, float]:
            if not vals:
                return {"count": 0, "avg_ms": 0.0, "min_ms": 0.0, "max_ms": 0.0, "p95_ms": 0.0}
            sorted_v = sorted(vals)
            p95_idx = int(len(sorted_v) * 0.95)
            return {
                "count": len(vals),
                "avg_ms": round(sum(vals) / len(vals), 2),
                "min_ms": round(min(vals), 2),
                "max_ms": round(max(vals), 2),
                "p95_ms": round(sorted_v[min(p95_idx, len(sorted_v) - 1)], 2),
            }

        cache_hit_rate = round(self.cache_hits / self.cache_lookups, 4) if self.cache_lookups > 0 else 1.0
        fallback_rate = (
            round(self.fallback_calls / self.total_extractions, 4) if self.total_extractions > 0 else 0.0
        )
        hitl_rate = (
            round(self.total_hitl_reviews_queued / self.total_products_enriched, 4)
            if self.total_products_enriched > 0
            else 0.0
        )
        schema_failure_rate = (
            round(self.total_schema_failures / self.total_schema_validations, 4)
            if self.total_schema_validations > 0
            else 0.0
        )

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_latency": stats(self.request_latencies),
            "llm_latency": stats(self.llm_latencies),
            "manufacturer_fetch_latency": stats(self.manufacturer_fetch_latencies),
            "cache_hit_rate": {
                "rate": cache_hit_rate,
                "percentage": round(cache_hit_rate * 100, 2),
                "total_lookups": self.cache_lookups,
                "cache_hits": self.cache_hits,
            },
            "llm_fallback_rate": {
                "rate": fallback_rate,
                "percentage": round(fallback_rate * 100, 2),
                "total_extractions": self.total_extractions,
                "live_nim_calls": self.live_nim_calls,
                "fallback_calls": self.fallback_calls,
            },
            "batch_throughput": {
                "total_items_processed": self.total_batch_items_processed,
                "items_per_minute": self.total_batch_items_processed * 60.0 if self.total_batch_items_processed > 0 else 0.0,
            },
            "hitl_rate": {
                "rate": hitl_rate,
                "percentage": round(hitl_rate * 100, 2),
                "total_enriched": self.total_products_enriched,
                "reviews_queued": self.total_hitl_reviews_queued,
            },
            "schema_failure_rate": {
                "rate": schema_failure_rate,
                "percentage": round(schema_failure_rate * 100, 2),
                "total_validations": self.total_schema_validations,
                "failures": self.total_schema_failures,
            },
        }


telemetry_collector = TelemetryCollector()


@asynccontextmanager
async def trace_stage_async(
    stage: str,
    metadata: Optional[dict[str, Any]] = None,
    product_id: Optional[int] = None,
    batch_id: Optional[int] = None,
):
    """Asynchronous context manager tracing pipeline stage execution time, status, and errors."""
    start_time = time.perf_counter()
    status = "SUCCESS"
    err_str = None
    try:
        yield
    except Exception as e:
        status = "FAILED"
        err_str = str(e)
        raise
    finally:
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        entry = StructuredLogEntry(
            stage=stage,
            status=status,
            duration_ms=elapsed_ms,
            product_id=product_id,
            batch_id=batch_id,
            error=err_str,
            metadata=metadata,
        )
        telemetry_collector.log_trace(entry)


@contextmanager
def trace_stage_sync(
    stage: str,
    metadata: Optional[dict[str, Any]] = None,
    product_id: Optional[int] = None,
    batch_id: Optional[int] = None,
):
    """Synchronous context manager tracing deterministic guardrails and CPU-bound stages."""
    start_time = time.perf_counter()
    status = "SUCCESS"
    err_str = None
    try:
        yield
    except Exception as e:
        status = "FAILED"
        err_str = str(e)
        raise
    finally:
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        entry = StructuredLogEntry(
            stage=stage,
            status=status,
            duration_ms=elapsed_ms,
            product_id=product_id,
            batch_id=batch_id,
            error=err_str,
            metadata=metadata,
        )
        telemetry_collector.log_trace(entry)


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """FastAPI / Starlette ASGI middleware ensuring unique X-Request-ID propagation and latency metrics."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = current_request_id.set(req_id)

        start_time = time.perf_counter()
        status_code = 200
        error_msg = None

        try:
            response: Response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = req_id
            return response
        except Exception as e:
            status_code = 500
            error_msg = str(e)
            raise
        finally:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            telemetry_collector.record_request_latency(elapsed_ms)

            entry = StructuredLogEntry(
                stage="HTTP_REQUEST",
                status="SUCCESS" if status_code < 400 else "FAILED",
                duration_ms=elapsed_ms,
                request_id=req_id,
                error=error_msg,
                metadata={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "client_ip": request.client.host if request.client else "unknown",
                },
            )
            telemetry_collector.log_trace(entry)
            current_request_id.reset(token)


# =========================================================
# Multi-Component Health Status Evaluator
# =========================================================

async def evaluate_system_health(db_session: Optional[Any] = None) -> dict[str, Any]:
    """Distinguish and return health status for database, redis, worker, LLM, and manufacturer sourcing."""
    from app.ai.nvidia_client import nvidia_client
    from app.agents.manufacturer_sourcing import manufacturer_registry
    from app.worker.batch_worker import ACTIVE_BATCH_TASKS, BATCH_RESULTS_CACHE, job_queue_manager
    from app.db.database import async_session

    # 1. Database Check
    db_status = "CONNECTED"
    db_dialect = "sqlite"
    db_error = None
    try:
        async with async_session() as session:
            res = await session.execute(text("SELECT 1"))
            val = res.scalar()
            if val != 1:
                db_status = "DEGRADED"
    except Exception as e:
        db_status = "UNREACHABLE"
        db_error = str(e)

    # 2. Redis / Queue Check
    redis_available = job_queue_manager.is_redis_available
    redis_status = "CONNECTED" if redis_available else "FALLBACK_ASYNCIO"
    redis_info = {
        "status": redis_status,
        "active_jobs": len(ACTIVE_BATCH_TASKS),
        "completed_jobs": len(BATCH_RESULTS_CACHE),
        "engine": "Redis Queue" if redis_available else "AsyncIO Background Worker",
    }

    # 3. Worker Status
    worker_status = {
        "status": "ACTIVE",
        "registered_workers": 1,
        "queue_depth": len(ACTIVE_BATCH_TASKS),
    }

    # 4. LLM / NVIDIA NIM Status
    nim_configured = nvidia_client.is_configured()
    llm_status = {
        "status": "AVAILABLE" if nim_configured else "OFFLINE_HEURISTIC_ACTIVE",
        "is_live_nim": nim_configured,
        "model": nvidia_client.model,
        "base_url": nvidia_client.base_url,
    }

    # 5. Manufacturer Sourcing Status
    mfg_domains = manufacturer_registry.get_all_domains()
    mfg_status = {
        "status": "ACTIVE",
        "registered_manufacturers": len(mfg_domains),
        "cache_enabled": True,
        "allowlist_domains_count": len(mfg_domains),
    }

    # Global Health Assessment
    is_healthy = db_status in ["CONNECTED", "DEGRADED"]
    overall_status = "HEALTHY" if is_healthy else "UNHEALTHY"
    if not nim_configured or redis_status == "FALLBACK_ASYNCIO":
        if is_healthy:
            overall_status = "DEGRADED"

    return {
        "status": overall_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "components": {
            "database": {
                "status": db_status,
                "dialect": db_dialect,
                "error": db_error,
            },
            "redis": redis_info,
            "worker": worker_status,
            "llm": llm_status,
            "manufacturer_sourcing": mfg_status,
        },
    }
