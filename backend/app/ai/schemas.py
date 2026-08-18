from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class ExtractedAttributes(BaseModel):
    brand: Optional[str] = Field(default=None, description="Extracted brand or manufacturer")
    item_type: Optional[str] = Field(default=None, description="Product category / item type (e.g. Dishwasher, Belt)")
    mpn: Optional[str] = Field(default=None, description="Manufacturer Part Number")
    voltage: Optional[str] = Field(default=None, description="Voltage rating (e.g. 120 V)")
    dimensions: Optional[str] = Field(default=None, description="Physical dimensions or size")
    mounting: Optional[str] = Field(default=None, description="Mounting type (e.g. Leg, Built-in)")
    material: Optional[str] = Field(default=None, description="Product material (e.g. Stainless Steel, SST)")
    raw_specs: dict[str, Any] = Field(default_factory=dict, description="Additional key-value specifications")


class ChannelDescriptions(BaseModel):
    invoice_desc: str = Field(..., description="<= 40 chars, ALL CAPS ERP description")
    mobile_desc: str = Field(..., description="60-80 chars B2B mobile description")
    product_title: str = Field(..., description="E-commerce product title")
    long_desc: str = Field(..., description="Full structured catalog paragraph")
    short_desc: str = Field(..., description="Concise summary string")


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
    status: str = Field(
        default="enriched",
        description="Pipeline processing status (e.g. enriched, fallback, failed)",
    )
    confidence_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Extraction confidence score from 0.0 to 1.0",
    )
    delivery_record_preview: Optional[dict[str, Any]] = None


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
    confidence_score: float
    status: str
    needs_review: bool
    attributes: ExtractedAttributes


class BatchEnrichmentResponse(BaseModel):
    total_items: int
    high_confidence_count: int
    review_needed_count: int
    average_confidence: float
    items: list[BatchItemResult]
    export_ready: bool = True
