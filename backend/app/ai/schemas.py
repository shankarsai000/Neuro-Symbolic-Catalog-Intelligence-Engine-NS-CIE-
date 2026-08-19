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
    series: Optional[str] = Field(default=None, description="Product series line (e.g. Professional Series, Eco Series)")
    mfr_url: Optional[str] = Field(default=None, description="Official manufacturer datasheet/support URL")
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
    review_tier: str = Field(default="AUTO_APPROVED", description="AUTO_APPROVED (>=0.90), REVIEW (0.75-0.89), HITL_REQUIRED (<0.75)")
    needs_review: bool = False
    explanation: str = Field(default="", description="Explainable mathematical derivation")
    field_confidences: dict[str, float] = Field(default_factory=dict, description="Field-level confidence breakdown")


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
        examples=["Appliance Dealers Cooperative (APPDE)"],
        description="Raw distributor / supplier string from input",
    )
    raw_brand: Optional[str] = Field(
        default=None,
        description="Raw brand string from input",
    )
    e1_brand: Optional[str] = Field(
        default=None,
        description="E1 brand field",
    )
    unilog_brand: Optional[str] = Field(
        default=None,
        description="Unilog brand field",
    )
    dib_brand: Optional[str] = Field(
        default=None,
        description="DIB brand field",
    )


class ExtractionViolation(BaseModel):
    field: str
    raw_value: Optional[str] = None
    reason: str
    action_taken: str  # "normalized", "rejected", "missing_required", "evidence_conflict"
    suggested_value: Optional[str] = None


class NeuroSymbolicValidationResult(BaseModel):
    category: str
    is_valid: bool = True
    passed_lov: bool = True
    passed_rules: bool = True
    violations: list[ExtractionViolation] = Field(default_factory=list)
    raw_llm_output: dict[str, Any] = Field(default_factory=dict)
    normalized_output: ExtractedAttributes
    needs_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)


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
    validation_result: Optional[NeuroSymbolicValidationResult] = None
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
    validation_result: Optional[NeuroSymbolicValidationResult] = None


class BatchEnrichmentResponse(BaseModel):
    total_items: int
    high_confidence_count: int
    review_needed_count: int
    average_confidence: float
    items: list[BatchItemResult]
    export_ready: bool = True
