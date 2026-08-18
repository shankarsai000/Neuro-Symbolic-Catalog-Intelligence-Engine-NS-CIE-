from __future__ import annotations

import datetime
from typing import Any, Optional
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def utc_now() -> datetime.datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.datetime.now(datetime.timezone.utc)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mfg_part_num: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    part_desc: Mapped[str] = mapped_column(Text, nullable=False)
    raw_manuf: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    canonical_brand: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(64), default="pending", index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    enrichment_runs: Mapped[list["EnrichmentRun"]] = relationship(
        "EnrichmentRun", back_populates="product", cascade="all, delete-orphan"
    )
    reviews: Mapped[list["ReviewQueue"]] = relationship(
        "ReviewQueue", back_populates="product", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_products_mpn_brand", "mfg_part_num", "canonical_brand"),
        Index("idx_products_status_created", "status", "created_at"),
    )


class EnrichmentRun(Base):
    __tablename__ = "enrichment_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    batch_job_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("batch_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_mode: Mapped[str] = mapped_column(String(64), default="OFFLINE_HEURISTIC")
    model_used: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Mathematical Confidence Breakdown
    confidence_score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    provenance_score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    lov_score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    rule_score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    # Multi-Channel Deliverables
    invoice_desc: Mapped[str] = mapped_column(String(40), nullable=False)
    mobile_desc: Mapped[str] = mapped_column(String(100), nullable=False)
    product_title: Mapped[str] = mapped_column(String(255), nullable=False)
    long_desc: Mapped[str] = mapped_column(Text, nullable=False)
    short_desc: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    status: Mapped[str] = mapped_column(String(64), default="completed", nullable=False)
    execution_time_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    product: Mapped["Product"] = relationship("Product", back_populates="enrichment_runs")
    attributes: Mapped[list["ExtractedAttribute"]] = relationship(
        "ExtractedAttribute", back_populates="enrichment_run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_enrichment_product_created", "product_id", "created_at"),
    )


class ExtractedAttribute(Base):
    __tablename__ = "extracted_attributes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    enrichment_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("enrichment_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attribute_label: Mapped[str] = mapped_column(String(128), nullable=False)
    attribute_value: Mapped[str] = mapped_column(Text, nullable=False)
    attribute_uom: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # Field-level Provenance
    source_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    source_type: Mapped[str] = mapped_column(String(64), default="distributor_feed", nullable=False)
    evidence_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    is_lov_validated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    enrichment_run: Mapped["EnrichmentRun"] = relationship(
        "EnrichmentRun", back_populates="attributes"
    )

    __table_args__ = (
        Index("idx_extracted_attr_run_label", "enrichment_run_id", "attribute_label"),
    )


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    mpn: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str] = mapped_column(String(512), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), default="html", nullable=False)
    http_status: Mapped[int] = mapped_column(Integer, default=200, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_text: Mapped[Text] = mapped_column(Text, nullable=False)
    parsed_evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    retrieved_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    evidences: Mapped[list["SourceEvidence"]] = relationship(
        "SourceEvidence", back_populates="source", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("brand", "mpn", name="uq_source_brand_mpn"),
        Index("idx_source_domain_brand", "domain", "brand"),
    )


class SourceEvidence(Base):
    __tablename__ = "source_evidences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    spec_key: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_snippet: Mapped[Text] = mapped_column(Text, nullable=False)
    extracted_value: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    source: Mapped["Source"] = relationship("Source", back_populates="evidences")

    __table_args__ = (
        Index("idx_source_evidence_source_key", "source_id", "spec_key"),
    )


class BatchJob(Base):
    __tablename__ = "batch_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    total_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    high_confidence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    review_needed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    average_confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(
        String(64), default="pending", index=True, nullable=False
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("idx_batch_jobs_status_created", "status", "created_at"),
    )


class ReviewQueue(Base):
    __tablename__ = "review_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    enrichment_run_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("enrichment_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    batch_job_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("batch_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    original_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    suggested_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    current_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(
        String(64), default="PENDING", index=True, nullable=False
    )
    assigned_to: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    resolved_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    product: Mapped["Product"] = relationship("Product", back_populates="reviews")
    actions: Mapped[list["ReviewAction"]] = relationship(
        "ReviewAction", back_populates="review", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_review_status_product", "status", "product_id"),
        Index("idx_review_created_status", "created_at", "status"),
    )


class ReviewAction(Base):
    __tablename__ = "review_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("review_queue.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    review: Mapped["ReviewQueue"] = relationship("ReviewQueue", back_populates="actions")

    __table_args__ = (
        Index("idx_review_actions_review_time", "review_id", "timestamp"),
    )


class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    dataset_path: Mapped[str] = mapped_column(String(512), nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    exact_match_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    field_accuracy: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    category_accuracy: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    schema_compliance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    uom_compliance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    fraction_compliance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    invoice_compliance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(64), default="completed", nullable=False)
    report_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    results: Mapped[list["BenchmarkResult"]] = relationship(
        "BenchmarkResult", back_populates="benchmark_run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_benchmark_run_status_created", "status", "created_at"),
    )


class BenchmarkResult(Base):
    __tablename__ = "benchmark_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    benchmark_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("benchmark_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    mpn: Mapped[str] = mapped_column(String(128), nullable=False)
    is_exact_match: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    field_scores_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    errors_json: Mapped[list[Any]] = mapped_column(JSON, default=list)

    benchmark_run: Mapped["BenchmarkRun"] = relationship(
        "BenchmarkRun", back_populates="results"
    )

    __table_args__ = (
        Index("idx_benchmark_results_run_row", "benchmark_run_id", "row_index"),
    )


class SchemaValidationResult(Base):
    __tablename__ = "schema_validation_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("batch_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    invalid_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    column_count_valid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    headers_valid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    order_valid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error_log_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    checked_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    timestamp: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        Index("idx_audit_events_type_entity", "event_type", "entity_type", "entity_id"),
        Index("idx_audit_events_timestamp", "timestamp"),
    )


# =========================================================================
# Phase 3: Master Data Tables (Taxonomies, Brands, UOMs, LOVs, Standards)
# =========================================================================

class MasterManufacturer(Base):
    __tablename__ = "master_manufacturers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    raw_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    brands: Mapped[list["MasterBrand"]] = relationship(
        "MasterBrand", back_populates="manufacturer", cascade="all, delete-orphan"
    )


class MasterBrand(Base):
    __tablename__ = "master_brands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical_name: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    manufacturer_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("master_manufacturers.id", ondelete="SET NULL"), nullable=True
    )
    aliases_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    domain: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    manufacturer: Mapped[Optional["MasterManufacturer"]] = relationship(
        "MasterManufacturer", back_populates="brands"
    )

    __table_args__ = (
        Index("idx_master_brands_canonical", "canonical_name"),
    )


class MasterUOM(Base):
    __tablename__ = "master_uoms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    raw_uom: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    standard_uom: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    dimension_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # length, voltage, amperage, weight
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class MasterFraction(Base):
    __tablename__ = "master_fractions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decimal_val: Mapped[float] = mapped_column(Float, unique=True, index=True, nullable=False)
    fraction_str: Mapped[str] = mapped_column(String(32), nullable=False)
    precision_32nd: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class MasterCategoryLOV(Base):
    __tablename__ = "master_category_lovs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(128), index=True, nullable=False)  # item_type, mounting, material, voltage
    attribute_name: Mapped[str] = mapped_column(String(128), nullable=False)
    lov_value: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        Index("idx_master_lov_cat_val", "category", "lov_value"),
    )


class MasterAttributeDefinition(Base):
    __tablename__ = "master_attribute_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attribute_name: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    data_type: Mapped[str] = mapped_column(String(64), default="string", nullable=False)  # string, number, uom_value, boolean
    is_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default_uom: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

