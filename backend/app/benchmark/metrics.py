"""
Metrics — Aggregated accuracy, pipeline, and sourcing metrics for benchmark runs.

Ground truth accuracy metrics exclude records marked GROUND_TRUTH_UNAVAILABLE.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from app.benchmark.golden_comparator import RecordComparison

logger = logging.getLogger(__name__)


@dataclass
class FieldMetrics:
    """Accuracy metrics computed from golden comparisons."""
    total_golden_records: int = 0
    total_fields_compared: int = 0
    exact_match_count: int = 0
    normalized_match_count: int = 0
    mismatch_count: int = 0
    expected_empty_count: int = 0
    field_accuracy: float = 0.0  # (exact + normalized) / (exact + normalized + mismatch)
    record_accuracy: float = 0.0  # records with 100% accuracy
    per_field_accuracy: dict[str, float] = field(default_factory=dict)
    worst_fields: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PipelineMetrics:
    """Pipeline execution metrics."""
    total_input_records: int = 0
    total_processed: int = 0
    total_failed: int = 0
    total_schema_valid: int = 0
    total_schema_invalid: int = 0
    ground_truth_available: int = 0
    ground_truth_unavailable: int = 0
    # Source mode breakdown
    nim_count: int = 0
    fallback_count: int = 0
    cache_hit_count: int = 0
    heuristic_count: int = 0
    # Latency (ms)
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    min_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    total_time_seconds: float = 0.0
    # HITL
    hitl_required_count: int = 0
    hitl_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_field_metrics(comparisons: list[RecordComparison]) -> FieldMetrics:
    """Compute field-level accuracy from golden comparisons."""
    metrics = FieldMetrics(total_golden_records=len(comparisons))

    # Aggregate field-level stats
    field_hits: dict[str, int] = {}
    field_totals: dict[str, int] = {}

    for comp in comparisons:
        metrics.exact_match_count += comp.exact_matches
        metrics.normalized_match_count += comp.normalized_matches
        metrics.mismatch_count += comp.mismatches
        metrics.expected_empty_count += comp.expected_empty
        metrics.total_fields_compared += comp.total_compared_fields

        for fc in comp.field_comparisons:
            if fc.comparison_type == "EXPECTED_EMPTY":
                continue
            field_totals[fc.field_name] = field_totals.get(fc.field_name, 0) + 1
            if fc.comparison_type in ("EXACT_MATCH", "NORMALIZED_MATCH"):
                field_hits[fc.field_name] = field_hits.get(fc.field_name, 0) + 1

    # Overall field accuracy
    denom = metrics.exact_match_count + metrics.normalized_match_count + metrics.mismatch_count
    metrics.field_accuracy = (
        (metrics.exact_match_count + metrics.normalized_match_count) / denom
        if denom > 0
        else 0.0
    )

    # Record accuracy (% of records with 100% accuracy)
    perfect = sum(1 for c in comparisons if c.accuracy == 1.0)
    metrics.record_accuracy = perfect / len(comparisons) if comparisons else 0.0

    # Per-field accuracy
    for fld, total in field_totals.items():
        hits = field_hits.get(fld, 0)
        metrics.per_field_accuracy[fld] = round(hits / total, 4) if total > 0 else 0.0

    # Worst fields (sorted by lowest accuracy)
    sorted_fields = sorted(metrics.per_field_accuracy.items(), key=lambda x: x[1])
    metrics.worst_fields = [
        {"field": f, "accuracy": a, "total": field_totals.get(f, 0)}
        for f, a in sorted_fields[:20]
        if a < 1.0
    ]

    return metrics


def compute_pipeline_metrics(
    records: list[dict[str, Any]],
    matched_count: int,
    unavailable_count: int,
    total_time_seconds: float = 0.0,
) -> PipelineMetrics:
    """Compute pipeline execution metrics from per-record tracking data."""
    metrics = PipelineMetrics(
        total_input_records=len(records),
        ground_truth_available=matched_count,
        ground_truth_unavailable=unavailable_count,
        total_time_seconds=total_time_seconds,
    )

    latencies: list[float] = []

    for rec in records:
        if rec.get("status") == "SUCCESS":
            metrics.total_processed += 1
        else:
            metrics.total_failed += 1

        if rec.get("schema_valid"):
            metrics.total_schema_valid += 1
        else:
            metrics.total_schema_invalid += 1

        source_mode = rec.get("source_mode", "").lower()
        if source_mode == "nim" or source_mode == "nvidia":
            metrics.nim_count += 1
        elif source_mode == "fallback":
            metrics.fallback_count += 1
        elif source_mode == "cache":
            metrics.cache_hit_count += 1
        else:
            metrics.heuristic_count += 1

        if rec.get("review_required"):
            metrics.hitl_required_count += 1

        if rec.get("processing_time_ms"):
            latencies.append(float(rec["processing_time_ms"]))

    # Latency stats
    if latencies:
        latencies.sort()
        metrics.avg_latency_ms = sum(latencies) / len(latencies)
        metrics.min_latency_ms = latencies[0]
        metrics.max_latency_ms = latencies[-1]
        metrics.p50_latency_ms = latencies[len(latencies) // 2]
        p95_idx = min(int(len(latencies) * 0.95), len(latencies) - 1)
        p99_idx = min(int(len(latencies) * 0.99), len(latencies) - 1)
        metrics.p95_latency_ms = latencies[p95_idx]
        metrics.p99_latency_ms = latencies[p99_idx]

    metrics.hitl_rate = (
        metrics.hitl_required_count / metrics.total_input_records
        if metrics.total_input_records > 0
        else 0.0
    )

    return metrics


def save_metrics(
    field_metrics: FieldMetrics,
    pipeline_metrics: PipelineMetrics,
    output_dir: Path,
) -> tuple[Path, Path]:
    """Write metrics to output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)

    field_path = output_dir / "field_metrics.json"
    field_path.write_text(json.dumps(field_metrics.to_dict(), indent=2), encoding="utf-8")

    pipeline_path = output_dir / "pipeline_metrics.json"
    pipeline_path.write_text(json.dumps(pipeline_metrics.to_dict(), indent=2), encoding="utf-8")

    return field_path, pipeline_path
