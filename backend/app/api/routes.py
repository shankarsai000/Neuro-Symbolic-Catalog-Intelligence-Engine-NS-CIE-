from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.guardrails import (
    decimal_to_fraction,
    enforce_uom_spacing,
    format_invoice_desc,
)
from app.core.sanitizer import clean_placeholders

router = APIRouter()


class HealthResponse(BaseModel):
    status: str = Field(..., examples=["NS-CIE Backend Active"])


class GuardrailsTestRequest(BaseModel):
    raw_text: str = Field(
        ...,
        examples=["50.25in 120v -- Unbranded --"],
        description="Raw input text to process through deterministic guardrails",
    )


class GuardrailsTestResponse(BaseModel):
    raw_text: str
    cleaned_text: str | None
    uom_spaced_text: str
    fraction_converted_text: str
    final_result: str
    invoice_desc_preview: str


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Return backend operational status."""
    return HealthResponse(status="NS-CIE Backend Active")


@router.post("/api/test-guardrails", response_model=GuardrailsTestResponse)
async def test_guardrails(payload: GuardrailsTestRequest) -> GuardrailsTestResponse:
    """Process raw input text through Unilog deterministic guardrails.

    Pipeline execution sequence:
    1. clean_placeholders (strips -- Unbranded --, -- No Unilog Brand --, etc.)
    2. enforce_uom_spacing (ensures 24in -> 24 in, 120v -> 120 V)
    3. decimal_to_fraction (converts 50.25 in -> 50-1/4 in)
    4. format_invoice_desc (previews 40-char max ALL-CAPS invoice description)
    """
    raw = payload.raw_text

    # Step 1: Placeholder sanitization
    sanitized = clean_placeholders(raw)

    # Step 2: Enforce UOM spacing & casing
    spaced = enforce_uom_spacing(sanitized) if sanitized is not None else ""

    # Step 3: Decimal to fraction conversion for inch measurements
    fractional = decimal_to_fraction(spaced)

    # Step 4: Invoice description format (40-char max, uppercase)
    invoice_desc = format_invoice_desc(fractional)

    return GuardrailsTestResponse(
        raw_text=raw,
        cleaned_text=sanitized,
        uom_spaced_text=spaced,
        fraction_converted_text=fractional,
        final_result=fractional,
        invoice_desc_preview=invoice_desc,
    )
