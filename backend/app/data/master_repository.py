from __future__ import annotations

import csv
import json
import logging
import re
from pathlib import Path
from typing import Any, Optional, Sequence
import pandas as pd
from rapidfuzz import fuzz, process, utils
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    MasterAttributeDefinition,
    MasterBrand,
    MasterCategoryLOV,
    MasterFraction,
    MasterManufacturer,
    MasterUOM,
    utc_now,
)

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent
SAMPLE_INPUT_PATH = DATA_DIR / "Unihack_ Sample Dataset - Input.csv"
DELIVERY_FORMAT_PATH = DATA_DIR / "Unihack_ Expected Output - Delivery Format.csv"

# Known distributor / wholesale tokens to prevent supplier-as-manufacturer pollution
DISTRIBUTOR_TOKENS = {
    "cooperative", "coop", "appde", "dealers", "distributor", "distributing",
    "wholesale", "supply llc", "electric inc", "building materials", "enterprises",
    "palmer donavin", "jam industrial", "fenton bros", "wesco", "graybar", "grainger"
}


class BrandRepository:
    """Repository managing Canonical Brands, supplier aliases, and fuzzy resolution."""

    def __init__(self) -> None:
        self.brand_mapping: dict[str, str] = {}
        self.canonical_brands: set[str] = set()
        self.brand_domains: dict[str, str] = {}
        self.brand_model_prefixes: dict[str, str] = {}

    def add_brand(
        self,
        canonical_name: str,
        aliases: Optional[list[str]] = None,
        domain: Optional[str] = None,
        model_prefixes: Optional[list[str]] = None,
    ) -> None:
        """Register a canonical legal brand and associated aliases."""
        clean_name = canonical_name.strip()
        self.canonical_brands.add(clean_name)
        self.brand_mapping[clean_name.lower()] = clean_name
        if domain:
            self.brand_domains[clean_name] = domain
        if aliases:
            for alias in aliases:
                clean_alias = alias.strip().lower()
                if clean_alias:
                    self.brand_mapping[clean_alias] = clean_name
        if model_prefixes:
            for pfx in model_prefixes:
                self.brand_model_prefixes[pfx.strip().lower()] = clean_name

    def get_canonical_brands(self) -> list[str]:
        """Return sorted list of all registered canonical brands."""
        return sorted(list(self.canonical_brands))

    def resolve_by_model_prefix(self, mpn: Optional[str]) -> Optional[str]:
        """Match MPN prefix against known manufacturer model code signatures."""
        if not mpn or not mpn.strip():
            return None
        clean_mpn = mpn.strip().lower()
        # Check longest prefixes first
        for pfx in sorted(self.brand_model_prefixes.keys(), key=len, reverse=True):
            if clean_mpn.startswith(pfx):
                return self.brand_model_prefixes[pfx]
        return None

    def resolve_canonical_brand(
        self, raw_input: Optional[str], score_cutoff: float = 80.0
    ) -> tuple[str, float]:
        """Resolve a raw supplier string to a Unilog Canonical Brand standard."""
        if not raw_input or not raw_input.strip():
            return "", 0.0

        cleaned = raw_input.strip()
        lowered = cleaned.lower()

        # 1. Exact direct lookup in alias mapping
        if lowered in self.brand_mapping:
            return self.brand_mapping[lowered], 1.0

        # 2. Substring token lookup for embedded brand names
        for alias, canonical in self.brand_mapping.items():
            if len(alias) >= 4 and re.search(r"\b" + re.escape(alias) + r"\b", lowered):
                return canonical, 0.95

        # 3. Weighted RapidFuzz matching against canonical brand set
        choices = list(self.canonical_brands)
        if not choices:
            return cleaned, 0.0

        match = process.extractOne(
            cleaned,
            choices,
            processor=utils.default_process,
            scorer=fuzz.WRatio,
            score_cutoff=score_cutoff,
        )

        if match:
            canonical_name, score, _ = match
            return canonical_name, round(score / 100.0, 3)

        return cleaned, 0.0

    async def load_from_db(self, db: AsyncSession) -> None:
        """Load brand standards from PostgreSQL master_brands table."""
        query = select(MasterBrand).where(MasterBrand.is_active.is_(True))
        result = await db.execute(query)
        records = result.scalars().all()
        for rec in records:
            aliases = rec.aliases_json if isinstance(rec.aliases_json, list) else []
            self.add_brand(rec.canonical_name, aliases, rec.domain)

    async def sync_to_db(self, db: AsyncSession) -> None:
        """Persist in-memory brand taxonomy to master_brands table."""
        for canonical_name in self.canonical_brands:
            aliases = [
                k for k, v in self.brand_mapping.items() if v == canonical_name and k != canonical_name.lower()
            ]
            domain = self.brand_domains.get(canonical_name)

            query = select(MasterBrand).where(MasterBrand.canonical_name == canonical_name)
            res = await db.execute(query)
            existing = res.scalar_one_or_none()

            if existing:
                existing.aliases_json = aliases
                existing.domain = domain
            else:
                brand_row = MasterBrand(
                    canonical_name=canonical_name,
                    aliases_json=aliases,
                    domain=domain,
                    is_active=True,
                    created_at=utc_now(),
                )
                db.add(brand_row)
        await db.flush()


class ManufacturerRepository:
    """Repository managing Legal Manufacturer Entities and supplier mappings."""

    def __init__(self) -> None:
        self.manufacturers: dict[str, dict[str, Any]] = {}
        self.brand_to_manufacturer: dict[str, str] = {}

    def add_manufacturer(
        self,
        name: str,
        canonical_brand: Optional[str] = None,
        country: Optional[str] = None,
        raw_name: Optional[str] = None,
    ) -> None:
        clean_name = name.strip()
        self.manufacturers[clean_name.lower()] = {
            "name": clean_name,
            "raw_name": raw_name or clean_name,
            "country": country,
        }
        if canonical_brand:
            self.brand_to_manufacturer[canonical_brand.strip().lower()] = clean_name

    def get_manufacturer_for_brand(self, canonical_brand: str) -> str:
        """Retrieve authoritative legal parent manufacturer name for a canonical brand."""
        if not canonical_brand:
            return ""
        lowered = canonical_brand.strip().lower()
        if lowered in self.brand_to_manufacturer:
            return self.brand_to_manufacturer[lowered]
        clean = canonical_brand.replace("®", "").replace("™", "").strip()
        return clean

    def get_all_manufacturers(self) -> list[dict[str, Any]]:
        return list(self.manufacturers.values())


class UOMRepository:
    """Repository managing Unit of Measure (UOM) normalization rules."""

    def __init__(self) -> None:
        self.uom_standards: dict[str, str] = {}

    def add_uom_rule(self, raw_uom: str, standard_uom: str) -> None:
        self.uom_standards[raw_uom.strip().lower()] = standard_uom.strip()

    def normalize_uom(self, raw_uom: str) -> str:
        if not raw_uom:
            return ""
        clean = raw_uom.strip().lower()
        return self.uom_standards.get(clean, raw_uom.strip())

    def get_standards_map(self) -> dict[str, str]:
        return dict(self.uom_standards)

    async def load_from_db(self, db: AsyncSession) -> None:
        query = select(MasterUOM).where(MasterUOM.is_active.is_(True))
        result = await db.execute(query)
        for rec in result.scalars().all():
            self.add_uom_rule(rec.raw_uom, rec.standard_uom)

    async def sync_to_db(self, db: AsyncSession) -> None:
        for raw_uom, std_uom in self.uom_standards.items():
            query = select(MasterUOM).where(MasterUOM.raw_uom == raw_uom)
            res = await db.execute(query)
            existing = res.scalar_one_or_none()
            if existing:
                existing.standard_uom = std_uom
            else:
                db.add(MasterUOM(raw_uom=raw_uom, standard_uom=std_uom, is_active=True))
        await db.flush()


class LOVRepository:
    """Repository managing List of Values (LOV) taxonomies across catalog categories."""

    def __init__(self) -> None:
        self.category_lovs: dict[str, set[str]] = {}

    def add_lov(self, category: str, value: str) -> None:
        cat_key = category.strip().lower()
        if cat_key not in self.category_lovs:
            self.category_lovs[cat_key] = set()
        self.category_lovs[cat_key].add(value.strip())

    def is_valid_lov(self, category: str, value: Optional[str]) -> bool:
        if not value:
            return False
        cat_key = category.strip().lower()
        val_clean = value.strip().lower()
        if cat_key in self.category_lovs:
            allowed = {v.lower() for v in self.category_lovs[cat_key]}
            return val_clean in allowed
        return False

    def get_allowed_lovs(self, category: str) -> list[str]:
        cat_key = category.strip().lower()
        if cat_key in self.category_lovs:
            return sorted(list(self.category_lovs[cat_key]))
        return []

    async def load_from_db(self, db: AsyncSession) -> None:
        query = select(MasterCategoryLOV).where(MasterCategoryLOV.is_active.is_(True))
        result = await db.execute(query)
        for rec in result.scalars().all():
            self.add_lov(rec.category, rec.lov_value)

    async def sync_to_db(self, db: AsyncSession) -> None:
        for cat_key, vals in self.category_lovs.items():
            for v in vals:
                query = select(MasterCategoryLOV).where(
                    MasterCategoryLOV.category == cat_key,
                    MasterCategoryLOV.lov_value == v,
                )
                res = await db.execute(query)
                if not res.scalar_one_or_none():
                    db.add(MasterCategoryLOV(category=cat_key, attribute_name=cat_key, lov_value=v, is_active=True))
        await db.flush()


class CategoryRepository:
    """Repository managing Category Definitions, hierarchy, and schema mappings."""

    def __init__(self) -> None:
        self.attribute_definitions: dict[str, dict[str, Any]] = {}

    def add_attribute_def(
        self,
        name: str,
        data_type: str = "string",
        is_required: bool = False,
        default_uom: Optional[str] = None,
        description: Optional[str] = None,
    ) -> None:
        self.attribute_definitions[name.strip()] = {
            "attribute_name": name.strip(),
            "data_type": data_type,
            "is_required": is_required,
            "default_uom": default_uom,
            "description": description,
        }

    def get_attribute_definition(self, name: str) -> Optional[dict[str, Any]]:
        return self.attribute_definitions.get(name.strip())

    def get_all_attribute_definitions(self) -> list[dict[str, Any]]:
        return list(self.attribute_definitions.values())


class MasterDataRepository:
    """Master Data Coordinator orchestrating Brands, LOVs, UOMs, Fractions, and Categories."""

    def __init__(self) -> None:
        self.brands = BrandRepository()
        self.manufacturers = ManufacturerRepository()
        self.uoms = UOMRepository()
        self.lovs = LOVRepository()
        self.categories = CategoryRepository()
        self.decimal_fractions: dict[float, str] = {}
        self._initialize_from_dataset_files()

    def _initialize_from_dataset_files(self) -> None:
        """Load authoritative brand standards and manufacturer entity mappings."""
        # 1. Base Canonical Brand Standards with Parent Legal Manufacturers & MPN Signatures
        base_canonical_brands = [
            (
                "FRIGIDAIRE®",
                "Rheem Manufacturing",
                ["frigidaire", "frigid air", "frigidaire appliances", "frigidaire professional"],
                "www.frigidaire.com",
                ["pdsh", "ffbd", "fgid", "fdpc", "ffcd", "fgip"],
            ),
            (
                "WHIRLPOOL®",
                "Whirlpool Corporation",
                ["whirlpool", "whirlpool corporation", "whirlpool appliances"],
                "www.whirlpool.com",
                ["wdts", "wdt", "wdp", "wdfe", "wdra", "wdf"],
            ),
            (
                "MILWAUKEE®",
                "Milwaukee Electric Tool Corporation",
                ["milwaukee", "milwaukee accessory", "milwaukee tool", "milwaukee electric"],
                "www.milwaukeetool.com",
                ["48-", "49-", "28", "27", "26"],
            ),
            (
                "FREUD®",
                "Robert Bosch Tool Corporation",
                ["freud", "freud inc", "freud tools"],
                "www.freudtools.com",
                ["dcb", "dbds", "ds", "d07", "d10", "d12"],
            ),
            (
                "DIABLO®",
                "Freud Tools / Robert Bosch Tool Corporation",
                ["diablo", "diablo saw blades", "diablo tools"],
                "www.diablotools.com",
                ["dcb", "dbds", "d07", "d10", "d12"],
            ),
            (
                "3M™",
                "3M Company",
                ["3m", "3m company", "3m commercial", "3m abrasives"],
                "www.3m.com",
                ["3mabr-", "3m", "71000", "7000"],
            ),
            (
                "DEWALT®",
                "Stanley Black & Decker",
                ["dewalt", "black & decker/dewlt", "black & decker", "dewalt industrial"],
                "www.dewalt.com",
                ["dwa", "dw", "dcm", "dcs"],
            ),
            (
                "SATCO®",
                "Satco Products Inc",
                ["satco", "satco prod inc", "satco products", "nuvo"],
                "www.satco.com",
                ["65-", "62-", "s9", "s11", "s12"],
            ),
            (
                "LEVITON®",
                "Leviton Manufacturing Co., Inc.",
                ["leviton", "leviton mfg co", "leviton manufacturing"],
                "www.leviton.com",
                ["lev", "5262", "5362"],
            ),
            (
                "FESTOOL®",
                "Festool GmbH",
                ["festool", "festool usa", "festool tools"],
                "www.festoolusa.com",
                ["57", "49", "20"],
            ),
            (
                "SOUTHWIRE®",
                "Southwire Company",
                ["southwire", "southwire/g turner", "southwire company"],
                "www.southwire.com",
                ["sw", "55"],
            ),
            (
                "KICHLER®",
                "Kichler Lighting LLC",
                ["kichler", "kichler lighting", "kichler lighting group"],
                "www.kichler.com",
                ["37", "42", "43", "45", "52", "55"],
            ),
            (
                "MAKITA®",
                "Makita Corporation",
                ["makita", "makita usa inc", "makita tools"],
                "www.makitatools.com",
                ["mak", "a-", "b-", "t-", "e-"],
            ),
            (
                "BOISE CASCADE®",
                "Boise Cascade Company",
                ["boise cascade", "boise cascade building materials"],
                "www.bc.com",
                ["1513", "1516"],
            ),
            (
                "KREG®",
                "Kreg Tool Company",
                ["kreg", "kreg tool company", "kreg tools"],
                "www.kregtool.com",
                ["kreg", "khc", "kpc"],
            ),
            (
                "EDGE SAFETY®",
                "Edge Eyewear",
                ["edge safety", "edge eyewear", "edge safety products"],
                "www.edgeeyewear.com",
                ["ts", "vs", "dz"],
            ),
            (
                "U.S. TAPE®",
                "U.S. Tape Company",
                ["u.s. tape", "u s tape company", "us tape"],
                "www.ustape.com",
                ["58", "59"],
            ),
            (
                "PARKSITE®",
                "Parksite Inc.",
                ["parksite", "parksite inc"],
                "www.parksite.com",
                ["pk"],
            ),
            (
                "PHILIPS LIGHTING®",
                "Signify N.V.",
                ["philips", "philips lighting", "phillips lighting"],
                "www.lighting.philips.com",
                ["pl"],
            ),
            (
                "SQUARE D®",
                "Schneider Electric",
                ["square d", "squared", "square d company"],
                "www.se.com",
                ["hom", "qo", "pk"],
            ),
            (
                "EATON®",
                "Eaton Corporation",
                ["eaton", "eaton corporation", "eaton electrical", "cutler-hammer"],
                "www.eaton.com",
                ["br", "ch"],
            ),
            (
                "BOSCH®",
                "Robert Bosch GmbH",
                ["bosch", "robert bosch", "bosch power tools"],
                "www.boschtools.com",
                ["11", "12", "16", "31", "40"],
            ),
            (
                "KLEIN TOOLS®",
                "Klein Tools Inc.",
                ["klein tools", "klein", "klein tools inc"],
                "www.kleintools.com",
                ["d2", "11", "32"],
            ),
            (
                "MIRKA®",
                "Mirka Ltd.",
                ["mirka", "mirka abrasives", "mirka abrasives inc", "mirus"],
                "www.mirka.com",
                ["mirk", "23-", "9a-"],
            ),
        ]

        for canonical, manufacturer, aliases, domain, prefixes in base_canonical_brands:
            self.brands.add_brand(canonical, aliases, domain, prefixes)
            self.manufacturers.add_manufacturer(
                name=manufacturer,
                canonical_brand=canonical,
                raw_name=canonical,
            )

        # 2. Master UOM Standards
        standard_uoms = {
            "in": "in", "inch": "in", "inches": "in", '"': "in",
            "ft": "ft", "foot": "ft", "feet": "ft", "'": "ft",
            "v": "V", "volt": "V", "volts": "V",
            "a": "A", "amp": "A", "amps": "A", "amperage": "A",
            "w": "W", "watt": "W", "watts": "W",
            "hz": "Hz", "hertz": "Hz",
            "rpm": "RPM",
            "dba": "dBA", "db": "dBA", "decibel": "dBA", "decibels": "dBA",
            "mm": "mm", "millimeter": "mm",
            "cm": "cm", "centimeter": "cm",
            "m": "m", "meter": "m",
            "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb",
            "oz": "oz", "ounce": "oz",
            "pk": "PK", "pack": "PK", "package": "PK",
            "pc": "PC", "piece": "PC", "pieces": "PC",
            "ea": "EA", "each": "EA",
            "gpm": "GPM",
            "psi": "PSI",
        }
        for r, s in standard_uoms.items():
            self.uoms.add_uom_rule(r, s)

        # 3. Fractional Standards
        self.decimal_fractions = {
            0.125: "1/8", 0.25: "1/4", 0.375: "3/8", 0.5: "1/2",
            0.625: "5/8", 0.75: "3/4", 0.875: "7/8", 0.0625: "1/16",
            0.1875: "3/16", 0.3125: "5/16", 0.4375: "7/16", 0.5625: "9/16",
            0.6875: "11/16", 0.8125: "13/16", 0.9375: "15/16",
        }

        # 4. Taxonomy LOVs
        taxonomy_lovs = {
            "item_type": [
                "Dishwasher", "Refrigerator", "Range", "Microwave", "Oven",
                "Cut-Off Disc", "Saw Blade", "Grinding Wheel", "Flap Disc", "Wire Wheel", "Drill Bit",
                "Faucet", "Kitchen Faucet", "Lavatory Faucet", "Commercial Faucet",
                "Pipe Fitting", "Tube Fitting", "Elbow", "Tee", "Coupling", "Adapter", "Union", "Nipple",
                "Switch", "Receptacle", "Wire", "Cable", "Luminaire", "Light Bulb", "Safety Glasses"
            ],
            "mounting": [
                "Built-In", "Built-in Mounting", "Freestanding", "Leg", "Leg Mounting", "Undercounter",
                "Wall Mount", "Panel Mount", "Surface Mount", "Flush Mount", "Deck Mount"
            ],
            "material": [
                "Stainless Steel", "SST", "Aluminum", "Carbon Steel", "Brass", "Solid Brass",
                "Chrome Plated Brass", "Copper", "Plastic", "Ceramic", "Carbide", "Bi-Metal"
            ],
            "voltage": ["120 V", "240 V", "208 V", "277 V", "480 V", "12 V", "18 V", "20 V"],
            "finish": ["Chrome", "Polished Chrome", "Brushed Nickel", "Matte Black", "Stainless Steel"],
            "grit": ["P36", "P40", "P60", "P80", "P120", "P150", "P180", "P220", "P320", "P400"],
            "arbor_size": ["1/4 in", "3/8 in", "1/2 in", "5/8 in", "7/8 in", "1 in", "20 mm", "5/8-11 in"],
        }
        for cat, vals in taxonomy_lovs.items():
            for v in vals:
                self.lovs.add_lov(cat, v)

        # 5. Attribute Definitions (schema metadata for each enrichment field)
        attribute_defs = [
            ("Item Type", "string", True, None, "Primary product category / type classification"),
            ("Brand", "string", True, None, "Canonical brand name"),
            ("Manufacturer", "string", True, None, "Legal parent manufacturer"),
            ("Voltage", "uom_value", False, "V", "Electrical voltage rating"),
            ("Amperage", "uom_value", False, "A", "Electrical current rating"),
            ("Wattage", "uom_value", False, "W", "Electrical power rating"),
            ("Material", "string", False, None, "Primary construction material"),
            ("Finish", "string", False, None, "Surface finish or color"),
            ("Mounting", "string", False, None, "Installation / mounting type"),
            ("Dimensions", "string", False, None, "Physical dimensions (L x W x H)"),
            ("Weight", "uom_value", False, "lb", "Product weight"),
        ]
        for name, data_type, is_required, default_uom, description in attribute_defs:
            self.categories.add_attribute_def(name, data_type, is_required, default_uom, description)

    def is_distributor(self, name: Optional[str]) -> bool:
        """Check if a supplier string represents a distributor or dealer rather than OEM manufacturer."""
        if not name:
            return False
        lowered = name.strip().lower()
        return any(t in lowered for t in DISTRIBUTOR_TOKENS)

    def resolve_entity(
        self,
        raw_desc: Optional[str] = None,
        mpn: Optional[str] = None,
        raw_brand: Optional[str] = None,
        raw_manuf: Optional[str] = None,
    ) -> tuple[str, str, str, float]:
        """
        Master Entity Resolution separating Supplier vs Brand vs Manufacturer.
        Returns:
            (canonical_brand, canonical_manufacturer, supplier_name, confidence)
        """
        supplier_name = raw_manuf.strip() if raw_manuf else ""
        canonical_brand = ""
        brand_score = 0.0

        # 1. First Priority: Resolve Brand from MPN Prefix (high-confidence OEM signature)
        if mpn:
            pfx_brand = self.brands.resolve_by_model_prefix(mpn)
            if pfx_brand:
                canonical_brand = pfx_brand
                brand_score = 1.0

        # 2. Second Priority: Resolve Brand from Product Description
        if not canonical_brand and raw_desc:
            desc_brand, score = self.brands.resolve_canonical_brand(raw_desc, score_cutoff=85.0)
            if score >= 0.85:
                canonical_brand = desc_brand
                brand_score = score

        # 3. Third Priority: Resolve Brand from explicit Raw Brand column (if not unbranded placeholder)
        if not canonical_brand and raw_brand:
            clean_b = raw_brand.strip()
            if clean_b and clean_b not in ["-- Unbranded --", "-- No Unilog Brand --", "-- No DIB Brand --", "-", "nan", "None"]:
                rb_brand, score = self.brands.resolve_canonical_brand(clean_b, score_cutoff=80.0)
                if score >= 0.80:
                    canonical_brand = rb_brand
                    brand_score = score

        # 4. Fourth Priority: Resolve Brand from Raw Manuf (ONLY if NOT a known distributor)
        if not canonical_brand and raw_manuf and not self.is_distributor(raw_manuf):
            rm_brand, score = self.brands.resolve_canonical_brand(raw_manuf, score_cutoff=80.0)
            if score >= 0.80:
                canonical_brand = rm_brand
                brand_score = score

        # 5. Default fallback if brand remains unresolved
        if not canonical_brand:
            canonical_brand = raw_brand if (raw_brand and not raw_brand.startswith("--")) else (raw_manuf or "")
            brand_score = 0.5 if canonical_brand else 0.0

        # 6. Retrieve Authoritative Parent Legal Manufacturer
        canonical_manufacturer = self.manufacturers.get_manufacturer_for_brand(canonical_brand)
        if not canonical_manufacturer:
            canonical_manufacturer = canonical_brand.replace("®", "").replace("™", "").strip()

        return canonical_brand, canonical_manufacturer, supplier_name, brand_score

    @property
    def uom_standards(self) -> dict[str, str]:
        return self.uoms.get_standards_map()

    @property
    def category_lovs(self) -> dict[str, set[str]]:
        return self.lovs.category_lovs

    @property
    def canonical_brands(self) -> set[str]:
        return self.brands.canonical_brands

    @property
    def brand_mapping(self) -> dict[str, str]:
        return self.brands.brand_mapping

    def resolve_canonical_brand(self, raw_input: Optional[str], score_cutoff: float = 80.0) -> tuple[str, float]:
        return self.brands.resolve_canonical_brand(raw_input, score_cutoff)

    def is_valid_lov(self, category: str, value: Optional[str]) -> bool:
        return self.lovs.is_valid_lov(category, value)

    def get_allowed_lovs(self, category: str) -> list[str]:
        return self.lovs.get_allowed_lovs(category)

    def get_all_master_brands(self) -> list[str]:
        return self.brands.get_canonical_brands()

    async def sync_all_to_db(self, db: AsyncSession) -> None:
        await self.brands.sync_to_db(db)
        await self.uoms.sync_to_db(db)
        await self.lovs.sync_to_db(db)

    async def load_all_from_db(self, db: AsyncSession) -> None:
        await self.brands.load_from_db(db)
        await self.uoms.load_from_db(db)
        await self.lovs.load_from_db(db)


master_data_repository = MasterDataRepository()
