from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.database import async_session, init_db
from app.db.models import AuditEvent, Product, ReviewAction, ReviewQueue
from main import app

client = TestClient(app)


@pytest.mark.asyncio
async def test_hitl_review_workflow_and_audit_logging():
    """Verify complete HITL review lifecycle with persistent database state, ReviewActions, and AuditEvents."""
    await init_db()

    # 1. Seed a low confidence item entering ReviewQueue
    async with async_session() as session:
        prod = Product(
            mfg_part_num="HITL-TEST-MPN",
            part_desc="Messy low confidence catalog item",
            canonical_brand="MILWAUKEE®",
        )
        session.add(prod)
        await session.flush()

        review = ReviewQueue(
            product_id=prod.id,
            field_name="INVOICE_DESC",
            original_value="Messy description",
            suggested_value="CUT OFF DISC 5 IN",
            current_value="CUT OFF DISC 5 IN",
            reason="Confidence score below 90% threshold",
            confidence=0.82,
            status="PENDING",
        )
        session.add(review)
        await session.commit()
        review_id = review.id
        product_id = prod.id

    # 2. List reviews via GET /api/reviews
    resp = client.get("/api/reviews")
    assert resp.status_code == 200
    items = resp.json()
    assert any(i["id"] == review_id for i in items)
    matched = next(i for i in items if i["id"] == review_id)
    assert matched["product_id"] == product_id
    assert matched["before_state"] == "Messy description"
    assert matched["after_state"] == "CUT OFF DISC 5 IN"
    assert matched["confidence"] == 0.82

    # 3. Edit review via POST /api/reviews/{id}/edit
    edit_payload = {
        "new_value": "5 IN METAL CUT OFF DISC",
        "reviewer": "john_auditor",
        "notes": "Auditor verified against physical packaging",
    }
    edit_resp = client.post(f"/api/reviews/{review_id}/edit", json=edit_payload)
    assert edit_resp.status_code == 200
    edit_json = edit_resp.json()
    assert edit_json["current_value"] == "5 IN METAL CUT OFF DISC"
    assert edit_json["status"] == "EDITED"
    assert edit_json["reviewer"] == "john_auditor"
    assert edit_json["resolved_at"] is not None

    # Verify ReviewAction and AuditEvent created for EDIT in database
    async with async_session() as session:
        actions = (await session.execute(select(ReviewAction).where(ReviewAction.review_id == review_id))).scalars().all()
        assert len(actions) == 1
        assert actions[0].action_type == "EDIT"
        assert actions[0].previous_value == "CUT OFF DISC 5 IN"
        assert actions[0].new_value == "5 IN METAL CUT OFF DISC"

        audits = (await session.execute(
            select(AuditEvent).where(AuditEvent.event_type == "HITL_REVIEW_EDITED")
        )).scalars().all()
        assert len(audits) >= 1
        assert audits[-1].entity_id == str(review_id)
        assert audits[-1].payload_json["new_value"] == "5 IN METAL CUT OFF DISC"

    # 4. Approve review via POST /api/reviews/{id}/approve
    approve_payload = {
        "reviewer": "sarah_lead",
        "notes": "Approved after manual correction",
    }
    appr_resp = client.post(f"/api/reviews/{review_id}/approve", json=approve_payload)
    assert appr_resp.status_code == 200
    appr_json = appr_resp.json()
    assert appr_json["status"] == "APPROVED"
    assert appr_json["reviewer"] == "sarah_lead"

    # Verify ReviewAction and AuditEvent created for APPROVE in database
    async with async_session() as session:
        actions = (await session.execute(select(ReviewAction).where(ReviewAction.review_id == review_id))).scalars().all()
        assert len(actions) == 2
        assert actions[1].action_type == "APPROVE"

        audits = (await session.execute(
            select(AuditEvent).where(AuditEvent.event_type == "HITL_REVIEW_APPROVED")
        )).scalars().all()
        assert len(audits) >= 1


@pytest.mark.asyncio
async def test_hitl_reject_workflow():
    """Verify rejecting a review item logs REJECT ReviewAction and AuditEvent."""
    await init_db()

    async with async_session() as session:
        prod = Product(
            mfg_part_num="REJECT-TEST-MPN",
            part_desc="Unverifiable item",
            canonical_brand="UNASSIGNED",
        )
        session.add(prod)
        await session.flush()

        review = ReviewQueue(
            product_id=prod.id,
            field_name="BRAND_NAME",
            original_value="Unknown",
            suggested_value="Hallucinated Brand",
            current_value="Hallucinated Brand",
            reason="Unverifiable source domain",
            confidence=0.40,
            status="PENDING",
        )
        session.add(review)
        await session.commit()
        review_id = review.id

    reject_payload = {
        "reviewer": "alex_auditor",
        "notes": "Cannot verify manufacturer domain",
    }
    rej_resp = client.post(f"/api/reviews/{review_id}/reject", json=reject_payload)
    assert rej_resp.status_code == 200
    assert rej_resp.json()["status"] == "REJECTED"

    async with async_session() as session:
        actions = (await session.execute(select(ReviewAction).where(ReviewAction.review_id == review_id))).scalars().all()
        assert len(actions) == 1
        assert actions[0].action_type == "REJECT"

        audits = (await session.execute(
            select(AuditEvent).where(AuditEvent.event_type == "HITL_REVIEW_REJECTED")
        )).scalars().all()
        assert len(audits) >= 1
