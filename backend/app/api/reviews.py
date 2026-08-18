from __future__ import annotations

import datetime
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db
from app.db.models import AuditEvent, Product, ReviewAction, ReviewQueue

router = APIRouter(prefix="/api/reviews", tags=["HITL Reviews"])


class ReviewItemResponse(BaseModel):
    id: int
    review_id: int
    product_id: int
    batch_id: Optional[int] = None
    mfg_part_num: str
    canonical_brand: Optional[str] = None
    field_name: str
    original_value: Optional[str] = None
    suggested_value: Optional[str] = None
    current_value: Optional[str] = None
    before_state: Optional[str] = None
    after_state: Optional[str] = None
    reason: str
    confidence: float
    reviewer: Optional[str] = None
    decision: Optional[str] = None
    status: str
    created_at: str
    resolved_at: Optional[str] = None


class ReviewActionRequest(BaseModel):
    reviewer: Optional[str] = Field(default="catalog_specialist", description="Reviewer name or identifier")
    notes: Optional[str] = Field(default=None, description="Human auditor notes")


class ReviewEditRequest(BaseModel):
    new_value: str = Field(..., description="Edited verified value")
    reviewer: Optional[str] = Field(default="catalog_specialist", description="Reviewer name or identifier")
    notes: Optional[str] = Field(default=None, description="Reason for modification")


def _format_review_item(r: ReviewQueue) -> ReviewItemResponse:
    mpn = r.product.mfg_part_num if r.product else "N/A"
    brand = r.product.canonical_brand if r.product else "N/A"
    return ReviewItemResponse(
        id=r.id,
        review_id=r.id,
        product_id=r.product_id,
        batch_id=r.batch_job_id,
        mfg_part_num=mpn,
        canonical_brand=brand,
        field_name=r.field_name,
        original_value=r.original_value,
        suggested_value=r.suggested_value,
        current_value=r.current_value,
        before_state=r.original_value,
        after_state=r.current_value,
        reason=r.reason,
        confidence=round(r.confidence, 3),
        reviewer=r.assigned_to,
        decision=r.status,
        status=r.status,
        created_at=r.created_at.isoformat() if r.created_at else "",
        resolved_at=r.resolved_at.isoformat() if r.resolved_at else None,
    )


@router.get("", response_model=list[ReviewItemResponse])
async def list_reviews(
    status: Optional[str] = Query(None, description="Filter by status: PENDING, APPROVED, REJECTED, EDITED"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[ReviewItemResponse]:
    """Retrieve persistent review queue items with optional status filtering and pagination."""
    query = (
        select(ReviewQueue)
        .options(selectinload(ReviewQueue.product))
        .order_by(desc(ReviewQueue.created_at))
        .offset(offset)
        .limit(limit)
    )

    if status:
        query = query.where(ReviewQueue.status == status.upper())

    result = await db.execute(query)
    reviews = result.scalars().all()

    return [_format_review_item(r) for r in reviews]


@router.get("/{review_id}", response_model=ReviewItemResponse)
async def get_review_detail(
    review_id: int,
    db: AsyncSession = Depends(get_db),
) -> ReviewItemResponse:
    """Retrieve details for a single HITL review item."""
    query = (
        select(ReviewQueue)
        .options(selectinload(ReviewQueue.product))
        .where(ReviewQueue.id == review_id)
    )
    result = await db.execute(query)
    r = result.scalar_one_or_none()

    if not r:
        raise HTTPException(status_code=404, detail="Review item not found")

    return _format_review_item(r)


@router.post("/{review_id}/approve", response_model=ReviewItemResponse)
async def approve_review(
    review_id: int,
    payload: ReviewActionRequest,
    db: AsyncSession = Depends(get_db),
) -> ReviewItemResponse:
    """Approve a review item, persist resolution in PostgreSQL/SQLite, and create ReviewAction and AuditEvent."""
    query = (
        select(ReviewQueue)
        .options(selectinload(ReviewQueue.product))
        .where(ReviewQueue.id == review_id)
    )
    result = await db.execute(query)
    r = result.scalar_one_or_none()

    if not r:
        raise HTTPException(status_code=404, detail="Review item not found")

    reviewer = payload.reviewer or "catalog_specialist"
    prev_val = r.current_value
    r.status = "APPROVED"
    r.assigned_to = reviewer
    r.resolved_at = datetime.datetime.now(datetime.timezone.utc)

    # 1. Log ReviewAction
    action = ReviewAction(
        review_id=r.id,
        action_type="APPROVE",
        previous_value=prev_val,
        new_value=r.current_value,
        user_notes=payload.notes,
    )
    db.add(action)

    # 2. Log AuditEvent
    audit = AuditEvent(
        event_type="HITL_REVIEW_APPROVED",
        entity_type="REVIEW_QUEUE",
        entity_id=str(r.id),
        payload_json={
            "reviewer": reviewer,
            "decision": "APPROVED",
            "notes": payload.notes,
            "resolved_value": r.current_value,
            "product_id": r.product_id,
        },
    )
    db.add(audit)
    await db.commit()

    return _format_review_item(r)


@router.post("/{review_id}/reject", response_model=ReviewItemResponse)
async def reject_review(
    review_id: int,
    payload: ReviewActionRequest,
    db: AsyncSession = Depends(get_db),
) -> ReviewItemResponse:
    """Reject a suggested enrichment extraction, record resolution, and create ReviewAction and AuditEvent."""
    query = (
        select(ReviewQueue)
        .options(selectinload(ReviewQueue.product))
        .where(ReviewQueue.id == review_id)
    )
    result = await db.execute(query)
    r = result.scalar_one_or_none()

    if not r:
        raise HTTPException(status_code=404, detail="Review item not found")

    reviewer = payload.reviewer or "catalog_specialist"
    prev_val = r.current_value
    r.status = "REJECTED"
    r.assigned_to = reviewer
    r.resolved_at = datetime.datetime.now(datetime.timezone.utc)

    # 1. Log ReviewAction
    action = ReviewAction(
        review_id=r.id,
        action_type="REJECT",
        previous_value=prev_val,
        new_value=None,
        user_notes=payload.notes,
    )
    db.add(action)

    # 2. Log AuditEvent
    audit = AuditEvent(
        event_type="HITL_REVIEW_REJECTED",
        entity_type="REVIEW_QUEUE",
        entity_id=str(r.id),
        payload_json={
            "reviewer": reviewer,
            "decision": "REJECTED",
            "notes": payload.notes,
            "product_id": r.product_id,
        },
    )
    db.add(audit)
    await db.commit()

    return _format_review_item(r)


@router.post("/{review_id}/edit", response_model=ReviewItemResponse)
async def edit_review(
    review_id: int,
    payload: ReviewEditRequest,
    db: AsyncSession = Depends(get_db),
) -> ReviewItemResponse:
    """Modify the current value of a review item, update product, and log ReviewAction and AuditEvent."""
    query = (
        select(ReviewQueue)
        .options(selectinload(ReviewQueue.product))
        .where(ReviewQueue.id == review_id)
    )
    result = await db.execute(query)
    r = result.scalar_one_or_none()

    if not r:
        raise HTTPException(status_code=404, detail="Review item not found")

    reviewer = payload.reviewer or "catalog_specialist"
    prev_val = r.current_value
    r.current_value = payload.new_value
    r.status = "EDITED"
    r.assigned_to = reviewer
    r.resolved_at = datetime.datetime.now(datetime.timezone.utc)

    # 1. Update Product if associated
    if r.product:
        if r.field_name == "INVOICE_DESC":
            r.product.invoice_desc = payload.new_value

    # 2. Log ReviewAction
    action = ReviewAction(
        review_id=r.id,
        action_type="EDIT",
        previous_value=prev_val,
        new_value=payload.new_value,
        user_notes=payload.notes,
    )
    db.add(action)

    # 3. Log AuditEvent
    audit = AuditEvent(
        event_type="HITL_REVIEW_EDITED",
        entity_type="REVIEW_QUEUE",
        entity_id=str(r.id),
        payload_json={
            "reviewer": reviewer,
            "decision": "EDITED",
            "previous_value": prev_val,
            "new_value": payload.new_value,
            "notes": payload.notes,
            "product_id": r.product_id,
        },
    )
    db.add(audit)
    await db.commit()

    return _format_review_item(r)
