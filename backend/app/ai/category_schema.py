from __future__ import annotations

import re
from typing import Any, Optional


class CategorySchema:
    """Deterministic schema definition and vocabulary constraints for a catalog category."""

    def __init__(
        self,
        name: str,
        allowed_attributes: set[str],
        required_attributes: set[str],
        allowed_lovs: dict[str, set[str]],
        synonym_mappings: dict[str, dict[str, str]],
        uom_rules: dict[str, str],
    ) -> None:
        self.name = name
        self.allowed_attributes = allowed_attributes
        self.required_attributes = required_attributes
        self.allowed_lovs = allowed_lovs
        self.synonym_mappings = synonym_mappings
        self.uom_rules = uom_rules


# Pre-defined deterministic category schemas
CATEGORY_SCHEMAS: dict[str, CategorySchema] = {
    "Dishwasher": CategorySchema(
        name="Dishwasher",
        allowed_attributes={
            "brand", "item_type", "mpn", "voltage", "dimensions", "mounting", "material", "amperage", "sound_level"
        },
        required_attributes={"brand", "item_type", "mpn", "voltage", "dimensions"},
        allowed_lovs={
            "item_type": {"Dishwasher", "Built-In Dishwasher", "Commercial Dishwasher"},
            "mounting": {"Built-In", "Freestanding", "Leg", "Undercounter"},
            "material": {"Stainless Steel", "Plastic", "Cast Iron", "Porcelain"},
            "voltage": {"120 V", "240 V", "120/240 V", "480 V"},
        },
        synonym_mappings={
            "material": {
                "ss": "Stainless Steel",
                "sst": "Stainless Steel",
                "stainless": "Stainless Steel",
                "stainless-steel": "Stainless Steel",
                "ss steel": "Stainless Steel",
            },
            "mounting": {
                "builtin": "Built-In",
                "built in": "Built-In",
                "built-in": "Built-In",
                "undercounter": "Built-In",
                "under-counter": "Built-In",
                "freestanding": "Freestanding",
                "free standing": "Freestanding",
                "leg mount": "Leg",
            },
            "voltage": {
                "120v": "120 V",
                "120 v": "120 V",
                "120 volt": "120 V",
                "120 volts": "120 V",
                "240v": "240 V",
                "240 v": "240 V",
            },
            "item_type": {
                "dw": "Dishwasher",
                "dish washer": "Dishwasher",
                "dish-washer": "Dishwasher",
            },
        },
        uom_rules={"voltage": "V", "amperage": "A", "dimensions": "in"},
    ),
    "Saw Blade": CategorySchema(
        name="Saw Blade",
        allowed_attributes={"brand", "item_type", "mpn", "dimensions", "material", "teeth", "arbor_size"},
        required_attributes={"brand", "item_type", "mpn", "dimensions"},
        allowed_lovs={
            "item_type": {"Saw Blade", "Circular Saw Blade", "Miter Saw Blade", "Table Saw Blade", "Reciprocating Saw Blade"},
            "material": {"Carbide", "High Speed Steel", "Diamond", "Bi-Metal", "Carbon Steel"},
        },
        synonym_mappings={
            "material": {
                "carbide tipped": "Carbide",
                "tct": "Carbide",
                "hss": "High Speed Steel",
                "bimetal": "Bi-Metal",
                "bi metal": "Bi-Metal",
            },
            "item_type": {
                "sawblade": "Saw Blade",
                "circular blade": "Circular Saw Blade",
                "blade": "Saw Blade",
            },
        },
        uom_rules={"dimensions": "in", "arbor_size": "in"},
    ),
    "Cut-Off Disc": CategorySchema(
        name="Cut-Off Disc",
        allowed_attributes={"brand", "item_type", "mpn", "dimensions", "material", "grit", "thickness", "arbor_size"},
        required_attributes={"brand", "item_type", "mpn", "dimensions"},
        allowed_lovs={
            "item_type": {"Cut-Off Disc", "Cut-Off Wheel", "Grinding Wheel", "Abrasive Disc"},
            "material": {"Aluminum Oxide", "Ceramic", "Silicon Carbide", "Zirconia Alumina"},
        },
        synonym_mappings={
            "item_type": {
                "cutoff disc": "Cut-Off Disc",
                "cut off disc": "Cut-Off Disc",
                "cut-off wheel": "Cut-Off Wheel",
                "cutoff wheel": "Cut-Off Wheel",
            },
            "material": {
                "alum oxide": "Aluminum Oxide",
                "alox": "Aluminum Oxide",
                "zirconia": "Zirconia Alumina",
            },
        },
        uom_rules={"dimensions": "in", "thickness": "in", "arbor_size": "in"},
    ),
    "General Commercial": CategorySchema(
        name="General Commercial",
        allowed_attributes={"brand", "item_type", "mpn", "voltage", "dimensions", "mounting", "material"},
        required_attributes={"brand", "item_type", "mpn"},
        allowed_lovs={
            "mounting": {"Built-In", "Freestanding", "Leg", "Wall Mount", "Surface Mount"},
            "material": {"Stainless Steel", "Aluminum", "Carbon Steel", "Carbide", "Plastic", "Brass", "Bronze"},
            "voltage": {"120 V", "240 V", "120/240 V", "480 V", "12 V", "18 V", "20 V"},
        },
        synonym_mappings={
            "material": {
                "ss": "Stainless Steel",
                "sst": "Stainless Steel",
                "stainless": "Stainless Steel",
                "alum": "Aluminum",
                "carbide steel": "Carbide",
            },
            "mounting": {
                "builtin": "Built-In",
                "built in": "Built-In",
                "freestanding": "Freestanding",
                "free standing": "Freestanding",
            },
            "voltage": {
                "120v": "120 V",
                "240v": "240 V",
            },
        },
        uom_rules={"voltage": "V", "amperage": "A", "dimensions": "in"},
    ),
}


class CategoryDetector:
    """Deterministic category classifier based on keyword patterns, MPN structure, and taxonomies."""

    @staticmethod
    def detect(raw_desc: str, mpn: Optional[str] = None, manufacturer: Optional[str] = None) -> CategorySchema:
        text = f"{raw_desc} {mpn or ''} {manufacturer or ''}".lower()

        if "dishwasher" in text or "dish washer" in text:
            return CATEGORY_SCHEMAS["Dishwasher"]

        if "cut-off" in text or "cutoff" in text or "cut off" in text:
            return CATEGORY_SCHEMAS["Cut-Off Disc"]

        if "blade" in text or "saw blade" in text:
            return CATEGORY_SCHEMAS["Saw Blade"]

        return CATEGORY_SCHEMAS["General Commercial"]


category_detector = CategoryDetector()
