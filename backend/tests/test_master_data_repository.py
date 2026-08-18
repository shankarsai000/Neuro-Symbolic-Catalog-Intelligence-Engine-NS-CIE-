from __future__ import annotations

import pytest
from app.agents.resolver import resolve_canonical_brand
from app.data.master_repository import (
    BrandRepository,
    CategoryRepository,
    LOVRepository,
    ManufacturerRepository,
    MasterDataRepository,
    UOMRepository,
    master_data_repository,
)
from app.db.database import async_session, init_db


def test_master_data_repository_initialization():
    """Verify MasterDataRepository loads base brands, UOMs, and fractions from files."""
    repo = MasterDataRepository()
    brands = repo.get_all_master_brands()
    assert len(brands) >= 20
    assert "FRIGIDAIRE®" in brands
    assert "FREUD®" in brands
    assert "MILWAUKEE®" in brands
    assert "MIRKA®" in brands
    assert "DEWALT®" in brands


def test_brand_resolution_real_examples():
    """Verify the 4 required real brand test cases resolve accurately."""
    # 1. frigid air -> FRIGIDAIRE®
    assert resolve_canonical_brand("frigid air") == "FRIGIDAIRE®"
    assert resolve_canonical_brand("Frigidaire Appliances") == "FRIGIDAIRE®"

    # 2. Freud Inc -> FREUD®
    assert resolve_canonical_brand("Freud Inc") == "FREUD®"
    assert resolve_canonical_brand("Freud Tools LLC (2435)") == "FREUD®"

    # 3. Milwaukee Accessory -> MILWAUKEE®
    assert resolve_canonical_brand("Milwaukee Accessory") == "MILWAUKEE®"
    assert resolve_canonical_brand("Milwaukee Tool (4031)") == "MILWAUKEE®"

    # 4. Mirka Abrasives -> MIRKA®
    assert resolve_canonical_brand("Mirka Abrasives") == "MIRKA®"
    assert resolve_canonical_brand("Mirka Abrasives Inc (MIRUS)") == "MIRKA®"


def test_unknown_brands_remain_unresolved():
    """Verify unknown brands are NOT falsely forced into a known brand standard."""
    unknown_1 = "Acme Custom Industrial Tools LLC"
    resolved_1 = resolve_canonical_brand(unknown_1)
    assert resolved_1 != "FRIGIDAIRE®"
    assert resolved_1 != "MILWAUKEE®"
    assert "Acme Custom Industrial" in resolved_1
    assert resolved_1 not in master_data_repository.get_all_master_brands()

    unknown_2 = "Delta Alpha Special Fabrication Co"
    resolved_2 = resolve_canonical_brand(unknown_2)
    assert resolved_2 != "DEWALT®"
    assert resolved_2 != "MIRKA®"
    assert resolved_2 not in master_data_repository.get_all_master_brands()

    # Direct repository resolution score for unknown string
    brand_repo = BrandRepository()
    brand_repo.add_brand("FRIGIDAIRE®", ["frigidaire"])
    brand_repo.add_brand("MILWAUKEE®", ["milwaukee"])
    
    res, score = brand_repo.resolve_canonical_brand("Completely Random Nonexistent Supplier 999", score_cutoff=80.0)
    assert score == 0.0
    assert res == "Completely Random Nonexistent Supplier 999"


def test_uom_repository_normalization():
    """Verify UOMRepository normalizes raw unit strings to canonical abbreviations."""
    uom_repo = master_data_repository.uoms
    assert uom_repo.normalize_uom("inch") == "in"
    assert uom_repo.normalize_uom("inches") == "in"
    assert uom_repo.normalize_uom('"') == "in"
    assert uom_repo.normalize_uom("volt") == "V"
    assert uom_repo.normalize_uom("volts") == "V"
    assert uom_repo.normalize_uom("amp") == "A"
    assert uom_repo.normalize_uom("amps") == "A"
    assert uom_repo.normalize_uom("lbs") == "lb"
    assert uom_repo.normalize_uom("pound") == "lb"


def test_lov_repository_validation():
    """Verify LOVRepository validates category taxonomy constraints."""
    lov_repo = master_data_repository.lovs

    assert lov_repo.is_valid_lov("item_type", "Dishwasher") is True
    assert lov_repo.is_valid_lov("item_type", "Cut-Off Disc") is True
    assert lov_repo.is_valid_lov("mounting", "Built-In") is True
    assert lov_repo.is_valid_lov("material", "Stainless Steel") is True
    assert lov_repo.is_valid_lov("voltage", "120 V") is True

    # Invalid LOV value
    assert lov_repo.is_valid_lov("item_type", "Nonexistent Artificial Category Value 123") is False


def test_category_repository_metadata():
    """Verify CategoryRepository manages schema attribute definitions."""
    cat_repo = master_data_repository.categories
    attr_def = cat_repo.get_attribute_definition("Item Type")
    assert attr_def is not None
    assert attr_def["is_required"] is True

    voltage_def = cat_repo.get_attribute_definition("Voltage")
    assert voltage_def is not None
    assert voltage_def["default_uom"] == "V"


@pytest.mark.asyncio
async def test_master_data_db_sync_and_load():
    """Verify database synchronization and loading of master data."""
    await init_db()
    async with async_session() as db:
        await master_data_repository.sync_all_to_db(db)
        await db.commit()

    # Load from DB into a clean repository instance
    fresh_repo = MasterDataRepository()
    async with async_session() as db:
        await fresh_repo.load_all_from_db(db)

    assert "FRIGIDAIRE®" in fresh_repo.get_all_master_brands()
    assert fresh_repo.uoms.normalize_uom("inch") == "in"
    assert fresh_repo.lovs.is_valid_lov("item_type", "Dishwasher") is True
