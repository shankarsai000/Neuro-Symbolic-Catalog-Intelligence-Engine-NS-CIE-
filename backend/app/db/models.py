from __future__ import annotations

import datetime
from typing import Any, Optional
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mfg_part_num: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    part_desc: Mapped[str] = mapped_column(Text, nullable=False)
    raw_manuf: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    canonical_brand: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(64), default="pending", index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )

    enrichment_runs: Mapped[list["EnrichmentRun"]] = relationship("EnrichmentRun", back_populates="product")
    reviews: Mapped[list["ReviewQueue"]] = relationship("ReviewQueue", back_populates="product")


class EnrichmentRun(Base):
    __tablename__ = "enrichment_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    batch_job_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("batch_jobs.id"), nullable=True)
    source_mode: Mapped[str] = mapped_column(String(64), default="OFFLINE_HEURISTIC")  # LIVE_NIM, OFFLINE_HEURISTIC, CACHE
    model_used: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    
    # Mathematical Confidence Breakdown
    confidence_score: Mapped[float] = mapped_column(Float, default=1.0)
    provenance_score: Mapped[float] = mapped_column(Float, default=1.0)
    lov_score: Mapped[float] = mapped_column(Float, default=1.0)
    rule_score: Mapped[float] = mapped_column(Float, default=1.0)

    # Multi-Channel Deliverables
    invoice_desc: Mapped[str] = mapped_column(String(40), nullable=False)
    mobile_desc: Mapped[str] = mapped_column(String(100), nullable=False)
    product_title: Mapped[str] = mapped_column(String(255), nullable=False)
    long_desc: Mapped[str] = mapped_column(Text, nullable=False)
    short_desc: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    status: Mapped[str] = mapped_column(String(64), default="completed")
    execution_time_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )

    product: Mapped["Product"] = relationship("Product", back_populates="enrichment_runs")
    attributes: Mapped[list["ExtractedAttribute"]] = relationship("ExtractedAttribute", back_populates="enrichment_run")


class ExtractedAttribute(Base):
    __tablename__ = "extracted_attributes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    enrichment_run_id: Mapped[int] = mapped_column(Integer, ForeignKey("enrichment_runs.id"), nullable=False, index=True)
    attribute_label: Mapped[str] = mapped_column(String(128), nullable=False)
    attribute_value: Mapped[str] = mapped_column(Text, nullable=False)
    attribute_uom: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    
    # Field-level Provenance
    source_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    source_type: Mapped[str] = mapped_column(String(64), default="distributor_feed")  # manufacturer_official, distributor_feed, heuristic
    evidence_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    is_lov_validated: Mapped[bool] = mapped_column(Boolean, default=True)

    enrichment_run: Mapped["EnrichmentRun"] = relationship("EnrichmentRun", back_populates="attributes")


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    mpn: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str] = mapped_column(String(512), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), default="html")  # html, pdf
    http_status: Mapped[int] = mapped_column(Integer, default=200)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_text: Mapped[Text] = mapped_column(Text, nullable=False)
    parsed_evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    retrieved_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )


class SourceEvidence(Base):
    __tablename__ = "source_evidences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("sources.id"), nullable=False)
    spec_key: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_snippet: Mapped[Text] = mapped_column(Text, nullable=False)
    extracted_value: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)


class BatchJob(Base):
    __tablename__ = "batch_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    processed_items: Mapped[int] = mapped_column(Integer, default=0)
    high_confidence_count: Mapped[int] = mapped_column(Integer, default=0)
    review_needed_count: Mapped[int] = mapped_column(Integer, default=0)
    average_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(64), default="pending", index=True)  # pending, processing, completed, failed
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)


class ReviewQueue(Base):
    __tablename__ = "review_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), nullable=False)
    enrichment_run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    batch_job_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    original_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    suggested_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    current_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(64), default="PENDING", index=True)  # PENDING, APPROVED, REJECTED, EDITED
    assigned_to: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    resolved_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)

    product: Mapped["Product"] = relationship("Product", back_populates="reviews")
    actions: Mapped[list["ReviewAction"]] = relationship("ReviewAction", back_populates="review")


class ReviewAction(Base):
    __tablename__ = "review_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(Integer, ForeignKey("review_queue.id"), nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)  # APPROVE, REJECT, EDIT
    previous_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )

    review: Mapped["ReviewQueue"] = relationship("ReviewQueue", back_populates="actions")


class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    dataset_path: Mapped[str] = mapped_column(String(512), nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    exact_match_rate: Mapped[float] = mapped_column(Float, default=0.0)
    field_accuracy: Mapped[float] = mapped_column(Float, default=0.0)
    category_accuracy: Mapped[float] = mapped_column(Float, default=0.0)
    schema_compliance: Mapped[float] = mapped_column(Float, default=0.0)
    uom_compliance: Mapped[float] = mapped_column(Float, default=0.0)
    fraction_compliance: Mapped[float] = mapped_column(Float, default=0.0)
    invoice_compliance: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(64), default="completed")
    report_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )


class BenchmarkResult(Base):
    __tablename__ = "benchmark_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    benchmark_run_id: Mapped[int] = mapped_column(Integer, ForeignKey("benchmark_runs.id"), nullable=False)
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    mpn: Mapped[str] = mapped_column(String(128), nullable=False)
    is_exact_match: Mapped[bool] = mapped_column(Boolean, default=False)
    field_scores_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    errors_json: Mapped[list[Any]] = mapped_column(JSON, default=list)


class SchemaValidationResult(Base):
    __tablename__ = "schema_validation_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, default=0)
    column_count_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    headers_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    order_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    error_log_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    checked_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    timestamp: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
