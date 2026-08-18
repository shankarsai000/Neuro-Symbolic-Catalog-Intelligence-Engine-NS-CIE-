from __future__ import annotations

import csv
import json
import logging
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


class BrandRepository:
    """Repository managing Canonical Brands, supplier aliases, and fuzzy resolution."""

    def __init__(self) -> None:
        self.brand_mapping: dict[str, str] = {}
        self.canonical_brands: set[str] = set()
        self.brand_domains: dict[str, str] = {}

    def add_brand(
        self, canonical_name: str, aliases: Optional[list[str]] = None, domain: Optional[str] = None
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

    def get_canonical_brands(self) -> list[str]:
        """Return sorted list of all registered canonical brands."""
        return sorted(list(self.canonical_brands))

    def resolve_canonical_brand(
        self, raw_input: Optional[str], score_cutoff: float = 80.0
    ) -> tuple[str, float]:
        """Resolve a raw supplier string to a Unilog Canonical Brand standard.

        If similarity is below score_cutoff, the brand remains unresolved (returns (raw_input, 0.0))
        preventing false forced mappings.
        """
        if not raw_input or not raw_input.strip():
            return "", 0.0

        cleaned = raw_input.strip()
        lowered = cleaned.lower()

        # 1. Exact direct lookup in alias mapping
        if lowered in self.brand_mapping:
            return self.brand_mapping[lowered], 1.0

        # 2. Weighted RapidFuzz matching against canonical brand set
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

        # Fallback to token_sort_ratio (preserves full token sequence matching)
        sort_match = process.extractOne(
            cleaned,
            choices,
            processor=utils.default_process,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=score_cutoff,
        )

        if sort_match:
            canonical_name, score, _ = sort_match
            return canonical_name, round(score / 100.0, 3)

        # Unknown brand remains unresolved
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

    def add_manufacturer(self, name: str, country: Optional[str] = None, raw_name: Optional[str] = None) -> None:
        clean_name = name.strip()
        self.manufacturers[clean_name.lower()] = {
            "name": clean_name,
            "raw_name": raw_name or clean_name,
            "country": country,
        }

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
            return True
        cat_key = category.strip().lower()
        allowed = self.category_lovs.get(cat_key)
        if not allowed:
            return True
        val_clean = value.strip().lower()
        return any(v.lower() == val_clean for v in allowed)

    def get_allowed_lovs(self, category: str) -> list[str]:
        cat_key = category.strip().lower()
        return sorted(list(self.category_lovs.get(cat_key, set())))

    async def load_from_db(self, db: AsyncSession) -> None:
        query = select(MasterCategoryLOV).where(MasterCategoryLOV.is_active.is_(True))
        result = await db.execute(query)
        for rec in result.scalars().all():
            self.add_lov(rec.category, rec.lov_value)

    async def sync_to_db(self, db: AsyncSession) -> None:
        for cat, values in self.category_lovs.items():
            for val in values:
                query = select(MasterCategoryLOV).where(
                    MasterCategoryLOV.category == cat, MasterCategoryLOV.lov_value == val
                )
                res = await db.execute(query)
                if not res.scalar_one_or_none():
                    db.add(MasterCategoryLOV(category=cat, attribute_name=cat, lov_value=val, is_active=True))
        await db.flush()


class CategoryRepository:
    """Repository managing Category Metadata and Schema Attribute Definitions."""

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
        """Load real supplier data, taxonomies, and delivery schemas from repository CSV files."""
        # 1. Base Canonical Brand Standards
        base_canonical_brands = [
            ("FRIGIDAIRE®", ["frigidaire", "frigid air", "frigidaire appliances"], "www.frigidaire.com"),
            ("MILWAUKEE®", ["milwaukee", "milwaukee accessory", "milwaukee tool", "milwaukee electric"], "www.milwaukeetool.com"),
            ("FREUD®", ["freud", "freud inc", "freud tools", "diablo", "diablo tools"], "www.freudtools.com"),
            ("MIRKA®", ["mirka", "mirka abrasives", "mirka abrasives inc", "mirus"], "www.mirka.com"),
            ("WHIRLPOOL®", ["whirlpool", "whirlpool corporation", "whirlpool appliances"], "www.whirlpool.com"),
            ("3M™", ["3m", "3m company", "3m commercial"], "www.3m.com"),
            ("DEWALT®", ["dewalt", "black & decker/dewlt", "black & decker", "dewalt industrial"], "www.dewalt.com"),
            ("SATCO®", ["satco", "satco prod inc", "satco products"], "www.satco.com"),
            ("LEVITON®", ["leviton", "leviton mfg co", "leviton manufacturing"], "www.leviton.com"),
            ("FESTOOL®", ["festool", "festool usa", "festool tools"], "www.festoolusa.com"),
            ("SOUTHWIRE®", ["southwire", "southwire/g turner", "southwire company"], "www.southwire.com"),
            ("KICHLER®", ["kichler", "kichler lighting", "kichler lighting group"], "www.kichler.com"),
            ("MAKITA®", ["makita", "makita usa inc", "makita tools"], "www.makitatools.com"),
            ("BOISE CASCADE®", ["boise cascade", "boise cascade building materials"], "www.bc.com"),
            ("KREG®", ["kreg", "kreg tool company", "kreg tools"], "www.kregtool.com"),
            ("EDGE SAFETY®", ["edge safety", "edge eyewear", "edge safety products"], "www.edgeeyewear.com"),
            ("U.S. TAPE®", ["u.s. tape", "u s tape company", "us tape"], "www.ustape.com"),
            ("PARKSITE®", ["parksite", "parksite inc"], "www.parksite.com"),
            ("PHILIPS LIGHTING®", ["philips", "philips lighting", "phillips lighting"], "www.lighting.philips.com"),
            ("DIABLO®", ["diablo", "diablo saw blades"], "www.diablotools.com"),
            ("SQUARE D®", ["square d", "squared", "square d company"], "www.se.com"),
            ("EATON®", ["eaton", "eaton corporation", "eaton electrical"], "www.eaton.com"),
            ("BOSCH®", ["bosch", "robert bosch", "bosch power tools"], "www.boschtools.com"),
            ("KLEIN TOOLS®", ["klein tools", "klein", "klein tools inc"], "www.kleintools.com"),
        ]

        for canonical, aliases, domain in base_canonical_brands:
            self.brands.add_brand(canonical, aliases, domain)
            self.manufacturers.add_manufacturer(canonical)

        # 2. Extract Real Supplier Names from Unihack Sample Dataset
        if SAMPLE_INPUT_PATH.exists():
            try:
                df = pd.read_csv(SAMPLE_INPUT_PATH, usecols=["Part_Manuf", "Unilog_Brand"], dtype=str)
                for _, row in df.iterrows():
                    manuf = str(row.get("Part_Manuf", "")).strip()
                    unilog_b = str(row.get("Unilog_Brand", "")).strip()

                    if manuf and manuf not in ["-", "nan", "None", "-- Unbranded --", "-- No Unilog Brand --"]:
                        self.manufacturers.add_manufacturer(manuf, raw_name=manuf)

                    if unilog_b and unilog_b not in ["-", "nan", "None", "-- Unbranded --", "-- No Unilog Brand --"]:
                        self.brands.add_brand(unilog_b, [unilog_b.lower()])
            except Exception as e:
                logger.warning(f"Error loading master brands from dataset: {e}")

        # 3. Master UOM Standards
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
            "deg": "°", "degree": "°", "degrees": "°",
            "gpm": "GPM", "gal/min": "GPM",
            "psi": "PSI", "psig": "PSI",
            "grit": "Grit",
        }
        for r, s in standard_uoms.items():
            self.uoms.add_uom_rule(r, s)

        # 4. Master Decimal-to-Fraction Conversions (32nd precision)
        self.decimal_fractions = {
            0.03125: "1/32", 0.0625: "1/16", 0.09375: "3/32", 0.125: "1/8",
            0.15625: "5/32", 0.1875: "3/16", 0.21875: "7/32", 0.25: "1/4",
            0.28125: "9/32", 0.3125: "5/16", 0.34375: "11/32", 0.375: "3/8",
            0.40625: "13/32", 0.4375: "7/16", 0.46875: "15/32", 0.5: "1/2",
            0.53125: "17/32", 0.5625: "9/16", 0.59375: "19/32", 0.625: "5/8",
            0.65625: "21/32", 0.6875: "11/16", 0.71875: "23/32", 0.75: "3/4",
            0.78125: "25/32", 0.8125: "13/16", 0.84375: "27/32", 0.875: "7/8",
            0.90625: "29/32", 0.9375: "15/16", 0.96875: "31/32",
            0.045: "3/64", 0.047: "3/64", 0.19: "3/16", 0.44: "7/16", 0.94: "15/16",
        }

        # 5. Master Taxonomy List of Values (LOVs)
        taxonomy_lovs = {
            "item_type": [
                # Appliances
                "Dishwasher", "Built-In Dishwasher", "Commercial Dishwasher",
                "Refrigerator", "Range", "Oven", "Washing Machine", "Dryer", "Water Heater",
                # Abrasives & Cutting Tools
                "Cut-Off Disc", "Cut-Off Wheel", "Sanding Belt", "Abrasive Disc",
                "Saw Blade", "Grinding Wheel", "Flap Disc", "Wire Wheel", "Drill Bit", "Carbide Bur",
                # Faucets
                "Faucet", "Kitchen Faucet", "Lavatory Faucet", "Commercial Faucet",
                "Pre-Rinse Faucet", "Utility Faucet", "Bar Faucet",
                # Fittings
                "Pipe Fitting", "Tube Fitting", "Elbow", "Tee", "Coupling",
                "Adapter", "Union", "Nipple", "Bushing", "Reducer", "Cap", "Plug", "Flange",
                # General Electrical & Industrial
                "Switch", "Receptacle", "Wire", "Cable",
                "Luminaire", "Light Bulb", "Safety Glasses", "Measuring Tape",
                "Pocket Hole Jig", "Router Bit", "Fastener", "Screw", "Connector"
            ],
            "mounting": [
                "Built-In", "Freestanding", "Leg", "Undercounter", "Wall Mount",
                "Panel Mount", "Surface Mount", "Flush Mount", "Ceiling Mount",
                "Direct Bury", "Track Mount", "Deck Mount", "Centerset", "Widespread", "Single Hole"
            ],
            "material": [
                "Stainless Steel", "SST", "Aluminum", "Carbon Steel", "Brass", "Solid Brass",
                "Chrome Plated Brass", "Copper", "Plastic", "Ceramic", "Zirconia", "Zirconia Alumina",
                "Carbide", "High Speed Steel", "Bi-Metal", "Aluminum Oxide", "Silicon Carbide", "Diamond",
                "PVC", "CPVC", "PEX", "Polycarbonate", "Rubber", "Cast Iron", "Ductile Iron", "Malleable Iron"
            ],
            "voltage": [
                "120 V", "240 V", "208 V", "277 V", "480 V", "12 V", "18 V",
                "20 V", "60 V", "120/240 V"
            ],
            "flow_rate": [
                "0.5 GPM", "1.0 GPM", "1.2 GPM", "1.5 GPM", "1.8 GPM", "2.0 GPM", "2.2 GPM"
            ],
            "connection_type": [
                "NPT", "MNPT", "FNPT", "Threaded", "Compression", "Socket Weld",
                "Butt Weld", "Flanged", "Push-to-Connect", "Soldered", "Press"
            ],
            "pressure_rating": [
                "125 LB", "150 LB", "150 PSI", "300 LB", "300 PSI", "600 PSI",
                "1000 PSI", "2000 PSI", "3000 PSI"
            ],
            "finish": [
                "Chrome", "Polished Chrome", "Brushed Nickel", "Matte Black",
                "Stainless Steel", "Brass", "Oil Rubbed Bronze"
            ],
            "grit": [
                "P36", "P40", "P60", "P80", "P120", "P150", "P180", "P220",
                "P320", "P400", "P600", "36 Grit", "60 Grit", "80 Grit", "120 Grit"
            ],
            "arbor_size": [
                "1/4 in", "3/8 in", "1/2 in", "5/8 in", "7/8 in", "1 in", "20 mm", "5/8-11 in"
            ]
        }
        for cat, vals in taxonomy_lovs.items():
            for v in vals:
                self.lovs.add_lov(cat, v)

        # 6. Delivery Schema Attribute Definitions
        schema_attributes = [
            ("Item Type", "string", True),
            ("Voltage", "uom_value", False, "V"),
            ("Mounting Type", "string", False),
            ("Material", "string", False),
            ("Color", "string", False),
            ("Amperage", "uom_value", False, "A"),
            ("Wattage", "uom_value", False, "W"),
            ("Flow Rate", "uom_value", False, "GPM"),
            ("Connection Type", "string", False),
            ("Connection Size", "uom_value", False, "in"),
            ("Pressure Rating", "uom_value", False, "PSI"),
            ("Finish", "string", False),
            ("Grit", "string", False),
            ("Arbor Size", "uom_value", False, "in"),
        ]
        for name, dtype, req, *extra in schema_attributes:
            uom = extra[0] if extra else None
            self.categories.add_attribute_def(name, dtype, req, uom)

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

    # Convenience delegating methods for backward compatibility
    def resolve_canonical_brand(self, raw_input: Optional[str], score_cutoff: float = 80.0) -> tuple[str, float]:
        return self.brands.resolve_canonical_brand(raw_input, score_cutoff)

    def is_valid_lov(self, category: str, value: Optional[str]) -> bool:
        return self.lovs.is_valid_lov(category, value)

    def get_allowed_lovs(self, category: str) -> list[str]:
        return self.lovs.get_allowed_lovs(category)

    def get_all_master_brands(self) -> list[str]:
        return self.brands.get_canonical_brands()

    async def sync_all_to_db(self, db: AsyncSession) -> None:
        """Persist entire in-memory master data catalog to PostgreSQL tables."""
        await self.brands.sync_to_db(db)
        await self.uoms.sync_to_db(db)
        await self.lovs.sync_to_db(db)

    async def load_all_from_db(self, db: AsyncSession) -> None:
        """Load entire master data catalog from PostgreSQL tables into memory."""
        await self.brands.load_from_db(db)
        await self.uoms.load_from_db(db)
        await self.lovs.load_from_db(db)


# Global singleton instance for application runtime
master_data_repository = MasterDataRepository()
