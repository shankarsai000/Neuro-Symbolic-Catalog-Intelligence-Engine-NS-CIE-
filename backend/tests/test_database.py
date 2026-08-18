from __future__ import annotations

import uuid
import pytest
from sqlalchemy import select
from app.db.database import async_session, init_db
from app.db.models import AuditEvent, Product


@pytest.mark.asyncio
async def test_database_initialization_and_product_crud():
    await init_db()
    unique_mpn = f"TEST-MPN-{uuid.uuid4().hex[:8]}"

    async with async_session() as session:
        # Create product
        prod = Product(
            mfg_part_num=unique_mpn,
            part_desc="Test Dishwasher 120v",
            raw_manuf="Frigidaire",
            canonical_brand="FRIGIDAIRE®",
            status="completed",
        )
        session.add(prod)
        await session.commit()

        # Query product
        q = select(Product).where(Product.mfg_part_num == unique_mpn)
        res = await session.execute(q)
        found = res.scalar_one_or_none()

        assert found is not None
        assert found.canonical_brand == "FRIGIDAIRE®"


@pytest.mark.asyncio
async def test_audit_event_logging():
    await init_db()
    unique_entity = f"audit-{uuid.uuid4().hex[:8]}"

    async with async_session() as session:
        audit = AuditEvent(
            event_type="SYSTEM_TEST",
            entity_type="TEST_SUITE",
            entity_id=unique_entity,
            payload_json={"status": "PASSED"},
        )
        session.add(audit)
        await session.commit()

        q = select(AuditEvent).where(AuditEvent.entity_id == unique_entity)
        res = await session.execute(q)
        found = res.scalar_one_or_none()

        assert found is not None
        assert found.event_type == "SYSTEM_TEST"
