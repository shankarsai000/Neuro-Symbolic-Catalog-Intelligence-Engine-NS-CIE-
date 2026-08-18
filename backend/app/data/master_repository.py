from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any, Optional
import pandas as pd
from rapidfuzz import process, utils

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent
SAMPLE_INPUT_PATH = DATA_DIR / "Unihack_ Sample Dataset - Input.csv"
DELIVERY_FORMAT_PATH = DATA_DIR / "Unihack_ Expected Output - Delivery Format.csv"


class MasterDataRepository:
    """Enterprise Master Data Repository managing master brands, LOV taxonomies, UOM standards, and fractions."""

    def __init__(self) -> None:
        self.brand_mapping: dict[str, str] = {}
        self.canonical_brands: set[str] = set()
        self.uom_standards: dict[str, str] = {}
        self.decimal_fractions: dict[float, str] = {}
        self.category_lovs: dict[str, set[str]] = {}
        self._initialize_master_data()

    def _initialize_master_data(self) -> None:
        """Load and build the master dataset from repository source files and enterprise taxonomies."""
        # 1. Base Canonical Brand Standards
        base_canonical = [
            "FRIGIDAIRE®", "MILWAUKEE®", "FREUD®", "MIRKA®", "WHIRLPOOL®",
            "3M™", "DEWALT®", "SATCO®", "LEVITON®", "FESTOOL®", "SOUTHWIRE®",
            "KICHLER®", "MAKITA®", "BOISE CASCADE®", "KREG®", "EDGE SAFETY®",
            "U.S. TAPE®", "PARKSITE®", "GE APPLIANCES®", "BOSCH®", "DIABLO®",
            "PHILIPS LIGHTING®", "LUTRON®", "SQUARE D®", "EATON®", "KLEIN TOOLS®",
            "IRWIN®", "CRAFTSMAN®", "STANLEY®", "LENOX®", "PROTO®", "RIDGID®"
        ]
        for b in base_canonical:
            self.canonical_brands.add(b)

        # 2. Extract Real Supplier Names from Unihack Sample Dataset
        if SAMPLE_INPUT_PATH.exists():
            try:
                df = pd.read_csv(SAMPLE_INPUT_PATH, usecols=["Part_Manuf", "Unilog_Brand"], dtype=str)
                for _, row in df.iterrows():
                    manuf = str(row.get("Part_Manuf", "")).strip()
                    unilog_b = str(row.get("Unilog_Brand", "")).strip()

                    if manuf and manuf not in ["-", "nan", "None", "-- Unbranded --", "-- No Unilog Brand --"]:
                        # Determine canonical entity
                        matched_brand = self._resolve_raw_manuf_to_brand(manuf)
                        if matched_brand:
                            self.brand_mapping[manuf.lower()] = matched_brand
                            self.canonical_brands.add(matched_brand)

                    if unilog_b and unilog_b not in ["-", "nan", "None", "-- Unbranded --", "-- No Unilog Brand --"]:
                        self.canonical_brands.add(unilog_b)
                        self.brand_mapping[unilog_b.lower()] = unilog_b
            except Exception as e:
                logger.warning(f"Error loading master brands from dataset: {e}")

        # Seed standard aliases
        standard_aliases = {
            "frigidaire": "FRIGIDAIRE®",
            "frigid air": "FRIGIDAIRE®",
            "whirlpool": "WHIRLPOOL®",
            "whirlpool corporation": "WHIRLPOOL®",
            "milwaukee": "MILWAUKEE®",
            "milwaukee accessory": "MILWAUKEE®",
            "milwaukee tool": "MILWAUKEE®",
            "freud": "FREUD®",
            "freud inc": "FREUD®",
            "diablo": "FREUD®",
            "mirka": "MIRKA®",
            "mirka abrasives": "MIRKA®",
            "dewalt": "DEWALT®",
            "black & decker/dewlt": "DEWALT®",
            "black & decker": "DEWALT®",
            "satco": "SATCO®",
            "satco prod inc": "SATCO®",
            "leviton": "LEVITON®",
            "leviton mfg co": "LEVITON®",
            "festool": "FESTOOL®",
            "festool usa": "FESTOOL®",
            "southwire": "SOUTHWIRE®",
            "southwire/g turner": "SOUTHWIRE®",
            "kichler": "KICHLER®",
            "kichler lighting": "KICHLER®",
            "makita": "MAKITA®",
            "makita usa inc": "MAKITA®",
            "boise cascade": "BOISE CASCADE®",
            "boise cascade building materials": "BOISE CASCADE®",
            "kreg": "KREG®",
            "kreg tool company": "KREG®",
            "edge eyewear": "EDGE SAFETY®",
            "u s tape company": "U.S. TAPE®",
            "parksite": "PARKSITE®",
            "phillips lighting": "PHILIPS LIGHTING®",
            "philips": "PHILIPS LIGHTING®",
            "3m": "3M™",
        }
        for k, v in standard_aliases.items():
            self.brand_mapping[k] = v
            self.canonical_brands.add(v)

        # 3. Master UOM Standards
        self.uom_standards = {
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
        }

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
            # Common imprecise distributor decimals
            0.045: "3/64", 0.047: "3/64", 0.19: "3/16", 0.44: "7/16", 0.94: "15/16",
        }

        # 5. Master List of Values (LOVs)
        self.category_lovs = {
            "item_type": {
                "Dishwasher", "Cut-Off Disc", "Sanding Belt", "Abrasive Disc",
                "Saw Blade", "Drill Bit", "Switch", "Receptacle", "Wire", "Cable",
                "Luminaire", "Light Bulb", "Safety Glasses", "Measuring Tape",
                "Pocket Hole Jig", "Router Bit", "Fastener", "Screw", "Connector"
            },
            "mounting": {
                "Built-In", "Freestanding", "Leg", "Under-Counter", "Wall Mount",
                "Panel Mount", "Surface Mount", "Flush Mount", "Ceiling Mount",
                "Direct Bury", "Track Mount"
            },
            "material": {
                "Stainless Steel", "SST", "Aluminum", "Carbon Steel", "Brass",
                "Copper", "Plastic", "Ceramic", "Zirconia", "Carbide", "Bi-Metal",
                "PVC", "Polycarbonate", "Rubber", "Cast Iron"
            },
            "voltage": {
                "120 V", "240 V", "208 V", "277 V", "480 V", "12 V", "18 V",
                "20 V", "60 V", "120/240 V"
            }
        }

    def _resolve_raw_manuf_to_brand(self, raw_manuf: str) -> Optional[str]:
        """Internal helper to match raw manufacturer name against base legal standards."""
        cleaned = raw_manuf.lower()
        if "frigidaire" in cleaned:
            return "FRIGIDAIRE®"
        if "milwaukee" in cleaned:
            return "MILWAUKEE®"
        if "freud" in cleaned or "diablo" in cleaned:
            return "FREUD®"
        if "mirka" in cleaned:
            return "MIRKA®"
        if "whirlpool" in cleaned:
            return "WHIRLPOOL®"
        if "dewalt" in cleaned or "black & decker" in cleaned:
            return "DEWALT®"
        if "satco" in cleaned:
            return "SATCO®"
        if "leviton" in cleaned:
            return "LEVITON®"
        if "festool" in cleaned:
            return "FESTOOL®"
        if "southwire" in cleaned:
            return "SOUTHWIRE®"
        if "kichler" in cleaned:
            return "KICHLER®"
        if "makita" in cleaned:
            return "MAKITA®"
        if "boise cascade" in cleaned:
            return "BOISE CASCADE®"
        if "kreg" in cleaned:
            return "KREG®"
        if "edge eyewear" in cleaned:
            return "EDGE SAFETY®"
        if "u s tape" in cleaned:
            return "U.S. TAPE®"
        if "parksite" in cleaned:
            return "PARKSITE®"
        if "phillips" in cleaned or "philips" in cleaned:
            return "PHILIPS LIGHTING®"
        if "3m" in cleaned:
            return "3M™"
        return None

    def resolve_canonical_brand(self, raw_input: Optional[str]) -> tuple[str, float]:
        """Resolve a raw supplier string to Unilog Master Legal Brand with confidence score."""
        if not raw_input or not raw_input.strip():
            return "", 0.0

        cleaned = raw_input.strip()
        lowered = cleaned.lower()

        # Direct map lookup
        if lowered in self.brand_mapping:
            return self.brand_mapping[lowered], 1.0

        # RapidFuzz similarity match
        choices = list(self.canonical_brands)
        match = process.extractOne(
            cleaned,
            choices,
            processor=utils.default_process,
            score_cutoff=70.0,
        )

        if match:
            canonical_name, score, _ = match
            return canonical_name, round(score / 100.0, 3)

        return cleaned, 0.5

    def is_valid_lov(self, category: str, value: Optional[str]) -> bool:
        """Verify whether an extracted value matches the master taxonomy LOV."""
        if not value:
            return True
        val_clean = value.strip().title()
        allowed = self.category_lovs.get(category)
        if not allowed:
            return True
        return any(v.lower() == val_clean.lower() for v in allowed)

    def get_allowed_lovs(self, category: str) -> list[str]:
        """Return allowed LOVs for a given attribute category."""
        return sorted(list(self.category_lovs.get(category, set())))

    def get_all_master_brands(self) -> list[str]:
        """Return all canonical master brands."""
        return sorted(list(self.canonical_brands))


# Singleton instance for application runtime
master_data_repository = MasterDataRepository()
