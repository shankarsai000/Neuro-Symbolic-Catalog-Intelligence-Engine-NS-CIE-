from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class ExtractedAttributes(BaseModel):
    brand: Optional[str] = Field(default=None, description="Extracted canonical brand or manufacturer")
    item_type: Optional[str] = Field(default=None, description="Product category / item type (e.g. Dishwasher, Belt)")
    mpn: Optional[str] = Field(default=None, description="Manufacturer Part Number")
    voltage: Optional[str] = Field(default=None, description="Voltage rating (e.g. 120 V)")
    dimensions: Optional[str] = Field(default=None, description="Physical dimensions or size")
    mounting: Optional[str] = Field(default=None, description="Mounting type (e.g. Leg, Built-In)")
    material: Optional[str] = Field(default=None, description="Product material (e.g. Stainless Steel, SST)")
    raw_specs: dict[str, Any] = Field(default_factory=dict, description="Additional key-value specifications")


class ChannelDescriptions(BaseModel):
    invoice_desc: str = Field(..., description="<= 40 chars, ALL CAPS ERP description")
    mobile_desc: str = Field(..., description="60-80 chars B2B mobile description")
    product_title: str = Field(..., description="E-commerce product title")
    long_desc: str = Field(..., description="Full structured catalog paragraph")
    short_desc: str = Field(..., description="Concise summary string")


class FieldProvenance(BaseModel):
    value: Optional[str] = None
    source_url: Optional[str] = None
    source_type: str = "distributor_feed"  # manufacturer_official_html, distributor_feed, heuristic
    evidence: Optional[str] = None
    retrieved_at: Optional[str] = None
    confidence: float = 1.0
    is_lov_validated: bool = True


class ProvenanceMap(BaseModel):
    brand: FieldProvenance
    item_type: FieldProvenance
    mpn: FieldProvenance
    voltage: FieldProvenance
    dimensions: FieldProvenance
    mounting: FieldProvenance
    material: FieldProvenance


class ConfidenceBreakdown(BaseModel):
    total_confidence: float = Field(..., ge=0.0, le=1.0)
    provenance_score: float = Field(..., ge=0.0, le=1.0)
    lov_match_score: float = Field(..., ge=0.0, le=1.0)
    rule_compliance_score: float = Field(..., ge=0.0, le=1.0)
    needs_review: bool = False


class EnrichmentRequest(BaseModel):
    mfg_part_num: str = Field(
        ...,
        examples=["PDSH4816AF"],
        description="Manufacturer Part Number",
    )
    part_desc: str = Field(
        ...,
        examples=["PDSH4816AF Dishwasher SS 120v 50.25in -- Unbranded --"],
        description="Raw catalog description string",
    )
    raw_manuf: Optional[str] = Field(
        default=None,
        examples=["FRIGIDAIRE"],
        description="Raw manufacturer name if available",
    )


class EnrichmentResponse(BaseModel):
    mfg_part_num: str
    attributes: ExtractedAttributes
    invoice_desc: str
    channel_descriptions: Optional[ChannelDescriptions] = None
    source_mode: str = Field(
        default="OFFLINE_HEURISTIC",
        description="Execution mode: LIVE_NIM, OFFLINE_HEURISTIC, MANUFACTURER_SOURCE, CACHE",
    )
    confidence_breakdown: Optional[ConfidenceBreakdown] = None
    confidence_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Calculated mathematical confidence score",
    )
    provenance: Optional[dict[str, Any]] = None
    delivery_record_preview: Optional[dict[str, Any]] = None
    needs_review: bool = False


class BatchEnrichmentRequest(BaseModel):
    items: list[EnrichmentRequest] = Field(
        ...,
        description="List of catalog items to enrich in batch",
    )


class BatchItemResult(BaseModel):
    mfg_part_num: str
    canonical_brand: str
    invoice_desc: str
    mobile_desc: str
    product_title: str
    source_mode: str
    confidence_score: float
    needs_review: bool
    attributes: ExtractedAttributes


class BatchEnrichmentResponse(BaseModel):
    total_items: int
    high_confidence_count: int
    review_needed_count: int
    average_confidence: float
    items: list[BatchItemResult]
    export_ready: bool = True
