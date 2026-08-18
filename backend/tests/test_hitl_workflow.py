from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.database import async_session, init_db
from app.db.models import Product, ReviewQueue
from main import app

client = TestClient(app)


@pytest.mark.asyncio
async def test_hitl_review_workflow_api():
    await init_db()

    # Seed product and review queue item
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
            reason="Confidence score below 90%",
            confidence=0.82,
            status="PENDING",
        )
        session.add(review)
        await session.commit()
        review_id = review.id

    # 1. List reviews via GET /api/reviews
    resp = client.get("/api/reviews")
    assert resp.status_code == 200
    items = resp.json()
    assert any(i["id"] == review_id for i in items)

    # 2. Edit review via POST /api/reviews/{id}/edit
    edit_payload = {"new_value": "5 IN METAL CUT OFF DISC", "notes": "Auditor verified"}
    edit_resp = client.post(f"/api/reviews/{review_id}/edit", json=edit_payload)
    assert edit_resp.status_code == 200
    assert edit_resp.json()["current_value"] == "5 IN METAL CUT OFF DISC"
    assert edit_resp.json()["status"] == "EDITED"

    # 3. Approve review via POST /api/reviews/{id}/approve
    approve_payload = {"notes": "Approved after manual correction"}
    appr_resp = client.post(f"/api/reviews/{review_id}/approve", json=approve_payload)
    assert appr_resp.status_code == 200
    assert appr_resp.json()["status"] == "APPROVED"
