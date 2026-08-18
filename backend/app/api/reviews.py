from __future__ import annotations

import datetime
from typing import Optional
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
    product_id: int
    mfg_part_num: str
    canonical_brand: Optional[str]
    field_name: str
    original_value: Optional[str]
    suggested_value: Optional[str]
    current_value: Optional[str]
    reason: str
    confidence: float
    status: str
    created_at: str
    resolved_at: Optional[str] = None


class ReviewActionRequest(BaseModel):
    notes: Optional[str] = Field(default=None, description="Human auditor notes")


class ReviewEditRequest(BaseModel):
    new_value: str = Field(..., description="Edited verified value")
    notes: Optional[str] = Field(default=None, description="Reason for modification")


@router.get("", response_model=list[ReviewItemResponse])
async def list_reviews(
    status: Optional[str] = Query(None, description="Filter by status: PENDING, APPROVED, REJECTED, EDITED"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[ReviewItemResponse]:
    """Retrieve persistent review queue items with optional status filtering."""
    query = (
        select(ReviewQueue)
        .options(selectinload(ReviewQueue.product))
        .order_by(desc(ReviewQueue.created_at))
        .limit(limit)
    )

    if status:
        query = query.where(ReviewQueue.status == status.upper())

    result = await db.execute(query)
    reviews = result.scalars().all()

    items: list[ReviewItemResponse] = []
    for r in reviews:
        mpn = r.product.mfg_part_num if r.product else "N/A"
        brand = r.product.canonical_brand if r.product else "N/A"
        items.append(
            ReviewItemResponse(
                id=r.id,
                product_id=r.product_id,
                mfg_part_num=mpn,
                canonical_brand=brand,
                field_name=r.field_name,
                original_value=r.original_value,
                suggested_value=r.suggested_value,
                current_value=r.current_value,
                reason=r.reason,
                confidence=round(r.confidence, 3),
                status=r.status,
                created_at=r.created_at.isoformat() if r.created_at else "",
                resolved_at=r.resolved_at.isoformat() if r.resolved_at else None,
            )
        )
    return items


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

    mpn = r.product.mfg_part_num if r.product else "N/A"
    brand = r.product.canonical_brand if r.product else "N/A"

    return ReviewItemResponse(
        id=r.id,
        product_id=r.product_id,
        mfg_part_num=mpn,
        canonical_brand=brand,
        field_name=r.field_name,
        original_value=r.original_value,
        suggested_value=r.suggested_value,
        current_value=r.current_value,
        reason=r.reason,
        confidence=round(r.confidence, 3),
        status=r.status,
        created_at=r.created_at.isoformat() if r.created_at else "",
        resolved_at=r.resolved_at.isoformat() if r.resolved_at else None,
    )


@router.post("/{review_id}/approve", response_model=ReviewItemResponse)
async def approve_review(
    review_id: int,
    payload: ReviewActionRequest,
    db: AsyncSession = Depends(get_db),
) -> ReviewItemResponse:
    """Approve a review item and log an auditable action."""
    query = (
        select(ReviewQueue)
        .options(selectinload(ReviewQueue.product))
        .where(ReviewQueue.id == review_id)
    )
    result = await db.execute(query)
    r = result.scalar_one_or_none()

    if not r:
        raise HTTPException(status_code=404, detail="Review item not found")

    r.status = "APPROVED"
    r.resolved_at = datetime.datetime.utcnow()

    # Log Review Action
    action = ReviewAction(
        review_id=r.id,
        action_type="APPROVE",
        previous_value=r.current_value,
        new_value=r.current_value,
        user_notes=payload.notes,
    )
    db.add(action)

    # Log Audit Event
    audit = AuditEvent(
        event_type="HITL_REVIEW_APPROVED",
        entity_type="REVIEW_QUEUE",
        entity_id=str(r.id),
        payload_json={"notes": payload.notes, "resolved_value": r.current_value},
    )
    db.add(audit)
    await db.commit()

    return await get_review_detail(review_id, db)


@router.post("/{review_id}/reject", response_model=ReviewItemResponse)
async def reject_review(
    review_id: int,
    payload: ReviewActionRequest,
    db: AsyncSession = Depends(get_db),
) -> ReviewItemResponse:
    """Reject a suggested enrichment extraction and log audit event."""
    query = (
        select(ReviewQueue)
        .options(selectinload(ReviewQueue.product))
        .where(ReviewQueue.id == review_id)
    )
    result = await db.execute(query)
    r = result.scalar_one_or_none()

    if not r:
        raise HTTPException(status_code=404, detail="Review item not found")

    r.status = "REJECTED"
    r.resolved_at = datetime.datetime.utcnow()

    action = ReviewAction(
        review_id=r.id,
        action_type="REJECT",
        previous_value=r.current_value,
        new_value=None,
        user_notes=payload.notes,
    )
    db.add(action)

    audit = AuditEvent(
        event_type="HITL_REVIEW_REJECTED",
        entity_type="REVIEW_QUEUE",
        entity_id=str(r.id),
        payload_json={"notes": payload.notes},
    )
    db.add(audit)
    await db.commit()

    return await get_review_detail(review_id, db)


@router.post("/{review_id}/edit", response_model=ReviewItemResponse)
async def edit_review(
    review_id: int,
    payload: ReviewEditRequest,
    db: AsyncSession = Depends(get_db),
) -> ReviewItemResponse:
    """Modify the current value of a review item with human audit trail."""
    query = (
        select(ReviewQueue)
        .options(selectinload(ReviewQueue.product))
        .where(ReviewQueue.id == review_id)
    )
    result = await db.execute(query)
    r = result.scalar_one_or_none()

    if not r:
        raise HTTPException(status_code=404, detail="Review item not found")

    prev_val = r.current_value
    r.current_value = payload.new_value
    r.status = "EDITED"
    r.resolved_at = datetime.datetime.utcnow()

    action = ReviewAction(
        review_id=r.id,
        action_type="EDIT",
        previous_value=prev_val,
        new_value=payload.new_value,
        user_notes=payload.notes,
    )
    db.add(action)

    audit = AuditEvent(
        event_type="HITL_REVIEW_EDITED",
        entity_type="REVIEW_QUEUE",
        entity_id=str(r.id),
        payload_json={
            "previous_value": prev_val,
            "new_value": payload.new_value,
            "notes": payload.notes,
        },
    )
    db.add(audit)
    await db.commit()

    return await get_review_detail(review_id, db)
