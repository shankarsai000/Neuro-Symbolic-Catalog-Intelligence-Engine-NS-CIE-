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
        description_strategy: str = "standard",
    ) -> None:
        self.name = name
        self.allowed_attributes = allowed_attributes
        self.required_attributes = required_attributes
        self.allowed_lovs = allowed_lovs
        self.synonym_mappings = synonym_mappings
        self.uom_rules = uom_rules
        self.description_strategy = description_strategy


# Pre-defined deterministic category schemas
CATEGORY_SCHEMAS: dict[str, CategorySchema] = {
    # 1. Faucets Specialized Intelligence
    "Faucets": CategorySchema(
        name="Faucets",
        allowed_attributes={
            "brand", "item_type", "mpn", "mounting", "material", "flow_rate",
            "finish", "spout_reach", "spout_type", "handle_count", "connection_size", "dimensions"
        },
        required_attributes={"brand", "item_type", "mpn", "mounting"},
        allowed_lovs={
            "item_type": {
                "Faucet", "Commercial Faucet", "Kitchen Faucet", "Lavatory Faucet",
                "Pre-Rinse Faucet", "Utility Faucet", "Bar Faucet"
            },
            "mounting": {
                "Deck Mount", "Wall Mount", "Centerset", "Widespread", "Single Hole", "Vessel", "Floor Mount"
            },
            "material": {
                "Brass", "Solid Brass", "Chrome Plated Brass", "Stainless Steel", "Zinc", "Bronze"
            },
            "flow_rate": {
                "0.5 GPM", "1.0 GPM", "1.2 GPM", "1.5 GPM", "1.8 GPM", "2.0 GPM", "2.2 GPM"
            },
            "finish": {
                "Chrome", "Polished Chrome", "Brushed Nickel", "Matte Black", "Stainless Steel", "Brass", "Oil Rubbed Bronze"
            },
        },
        synonym_mappings={
            "mounting": {
                "deck": "Deck Mount",
                "deck mount": "Deck Mount",
                "deck-mount": "Deck Mount",
                "wall": "Wall Mount",
                "wall mount": "Wall Mount",
                "wall-mount": "Wall Mount",
                "centerset": "Centerset",
                "center set": "Centerset",
                "center-set": "Centerset",
                "widespread": "Widespread",
                "wide spread": "Widespread",
                "single hole": "Single Hole",
                "1 hole": "Single Hole",
            },
            "flow_rate": {
                "0.5gpm": "0.5 GPM",
                "0.5 gpm": "0.5 GPM",
                "1.0gpm": "1.0 GPM",
                "1.2gpm": "1.2 GPM",
                "1.5gpm": "1.5 GPM",
                "1.5 gpm": "1.5 GPM",
                "1.8gpm": "1.8 GPM",
                "2.0gpm": "2.0 GPM",
                "2.2gpm": "2.2 GPM",
                "2.2 gpm": "2.2 GPM",
            },
            "material": {
                "chrome brass": "Chrome Plated Brass",
                "chrome-plated brass": "Chrome Plated Brass",
                "solid brass": "Solid Brass",
                "brass": "Brass",
                "ss": "Stainless Steel",
                "sst": "Stainless Steel",
                "stainless": "Stainless Steel",
            },
            "finish": {
                "cp": "Chrome",
                "polished chrome": "Polished Chrome",
                "bn": "Brushed Nickel",
                "brushed nickel": "Brushed Nickel",
                "mb": "Matte Black",
                "matte black": "Matte Black",
                "orb": "Oil Rubbed Bronze",
            },
            "item_type": {
                "faucet": "Faucet",
                "kitchen faucet": "Kitchen Faucet",
                "lav faucet": "Lavatory Faucet",
                "lavatory faucet": "Lavatory Faucet",
                "pre rinse": "Pre-Rinse Faucet",
                "prerinse": "Pre-Rinse Faucet",
            },
        },
        uom_rules={"flow_rate": "GPM", "spout_reach": "in", "dimensions": "in", "connection_size": "in"},
        description_strategy="faucet",
    ),

    # 2. Fittings Specialized Intelligence
    "Fittings": CategorySchema(
        name="Fittings",
        allowed_attributes={
            "brand", "item_type", "mpn", "material", "connection_type",
            "connection_size", "pressure_rating", "fitting_type", "dimensions"
        },
        required_attributes={"brand", "item_type", "mpn", "material", "connection_type"},
        allowed_lovs={
            "item_type": {
                "Pipe Fitting", "Tube Fitting", "Elbow", "Tee", "Coupling",
                "Adapter", "Union", "Nipple", "Bushing", "Reducer", "Cap", "Plug", "Flange"
            },
            "material": {
                "Brass", "Stainless Steel", "Copper", "Carbon Steel", "PVC", "CPVC",
                "Cast Iron", "Ductile Iron", "Malleable Iron", "PEX", "Bronze"
            },
            "connection_type": {
                "NPT", "MNPT", "FNPT", "Threaded", "Compression", "Socket Weld",
                "Butt Weld", "Flanged", "Push-to-Connect", "Soldered", "Press"
            },
            "pressure_rating": {
                "125 LB", "150 LB", "150 PSI", "300 LB", "300 PSI", "600 PSI",
                "1000 PSI", "2000 PSI", "3000 PSI"
            },
        },
        synonym_mappings={
            "connection_type": {
                "npt": "NPT",
                "mnpt": "MNPT",
                "fnpt": "FNPT",
                "fem npt": "FNPT",
                "female npt": "FNPT",
                "male npt": "MNPT",
                "threaded": "Threaded",
                "compression": "Compression",
                "sweat": "Soldered",
                "press fit": "Press",
            },
            "pressure_rating": {
                "150psi": "150 PSI",
                "300psi": "300 PSI",
                "600psi": "600 PSI",
                "150#": "150 LB",
                "300#": "300 LB",
                "150 lb": "150 LB",
                "300 lb": "300 LB",
            },
            "material": {
                "ss": "Stainless Steel",
                "sst": "Stainless Steel",
                "brs": "Brass",
                "cu": "Copper",
                "ci": "Cast Iron",
                "di": "Ductile Iron",
                "mi": "Malleable Iron",
            },
            "item_type": {
                "90 elbow": "Elbow",
                "45 elbow": "Elbow",
                "elbow": "Elbow",
                "tee": "Tee",
                "coupling": "Coupling",
                "adapter": "Adapter",
                "union": "Union",
            },
        },
        uom_rules={"connection_size": "in", "pressure_rating": "PSI", "dimensions": "in"},
        description_strategy="fitting",
    ),

    # 3. Abrasives & Cutting Tools Specialized Intelligence
    "Abrasives/Cutting Tools": CategorySchema(
        name="Abrasives/Cutting Tools",
        allowed_attributes={
            "brand", "item_type", "mpn", "dimensions", "material", "grit",
            "arbor_size", "thickness", "max_rpm", "pack_quantity"
        },
        required_attributes={"brand", "item_type", "mpn", "dimensions", "material"},
        allowed_lovs={
            "item_type": {
                "Cut-Off Disc", "Cut-Off Wheel", "Sanding Belt", "Abrasive Disc",
                "Saw Blade", "Grinding Wheel", "Flap Disc", "Wire Wheel", "Drill Bit", "Carbide Bur"
            },
            "material": {
                "Aluminum Oxide", "Ceramic", "Silicon Carbide", "Zirconia Alumina",
                "Diamond", "Carbide", "High Speed Steel", "Bi-Metal", "Carbon Steel"
            },
            "grit": {
                "P36", "P40", "P60", "P80", "P120", "P150", "P180", "P220",
                "P320", "P400", "P600", "36 Grit", "60 Grit", "80 Grit", "120 Grit"
            },
            "arbor_size": {
                "1/4 in", "3/8 in", "1/2 in", "5/8 in", "7/8 in", "1 in", "20 mm", "5/8-11 in"
            },
        },
        synonym_mappings={
            "material": {
                "alum oxide": "Aluminum Oxide",
                "alox": "Aluminum Oxide",
                "aluminum oxide": "Aluminum Oxide",
                "zirconia": "Zirconia Alumina",
                "zirconia alumina": "Zirconia Alumina",
                "carbide tipped": "Carbide",
                "tct": "Carbide",
                "hss": "High Speed Steel",
                "bimetal": "Bi-Metal",
                "bi metal": "Bi-Metal",
            },
            "grit": {
                "p-80": "P80",
                "80 grit": "P80",
                "p80": "P80",
                "p-120": "P120",
                "120 grit": "P120",
                "p120": "P120",
                "p-150": "P150",
                "150 grit": "P150",
                "p150": "P150",
                "p-180": "P180",
                "p-220": "P220",
                "p-320": "P320",
            },
            "arbor_size": {
                "7/8\"": "7/8 in",
                "5/8\"": "5/8 in",
                "20mm": "20 mm",
                "1\"": "1 in",
            },
            "item_type": {
                "cutoff disc": "Cut-Off Disc",
                "cut off disc": "Cut-Off Disc",
                "cut-off disc": "Cut-Off Disc",
                "cutoff wheel": "Cut-Off Wheel",
                "sanding disc": "Abrasive Disc",
                "sanding belt": "Sanding Belt",
                "sawblade": "Saw Blade",
                "saw blade": "Saw Blade",
            },
        },
        uom_rules={"dimensions": "in", "arbor_size": "in", "thickness": "in", "max_rpm": "RPM"},
        description_strategy="abrasive",
    ),

    # 4. Appliances Specialized Intelligence
    "Appliances": CategorySchema(
        name="Appliances",
        allowed_attributes={
            "brand", "item_type", "mpn", "voltage", "amperage", "dimensions",
            "mounting", "material", "sound_level", "capacity"
        },
        required_attributes={"brand", "item_type", "mpn", "voltage", "dimensions"},
        allowed_lovs={
            "item_type": {
                "Dishwasher", "Built-In Dishwasher", "Commercial Dishwasher",
                "Refrigerator", "Range", "Oven", "Washing Machine", "Dryer", "Water Heater"
            },
            "voltage": {"120 V", "240 V", "120/240 V", "208 V", "277 V", "480 V"},
            "amperage": {"10 A", "15 A", "20 A", "30 A", "50 A"},
            "mounting": {"Built-In", "Freestanding", "Leg", "Undercounter", "Wall Mount"},
            "material": {"Stainless Steel", "Plastic", "Cast Iron", "Porcelain"},
            "sound_level": {"38 dBA", "41 dBA", "44 dBA", "47 dBA", "50 dBA"},
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
        uom_rules={"voltage": "V", "amperage": "A", "sound_level": "dBA", "dimensions": "in"},
        description_strategy="appliance",
    ),

    # Legacy Backward-Compatible Aliases
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
                "ss": "Stainless Steel", "sst": "Stainless Steel", "stainless": "Stainless Steel",
            },
            "mounting": {
                "builtin": "Built-In", "built in": "Built-In", "undercounter": "Built-In", "freestanding": "Freestanding", "leg mount": "Leg",
            },
            "voltage": {
                "120v": "120 V", "240v": "240 V",
            },
            "item_type": {
                "dw": "Dishwasher", "dish washer": "Dishwasher",
            },
        },
        uom_rules={"voltage": "V", "amperage": "A", "dimensions": "in"},
        description_strategy="appliance",
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
            "material": {"carbide tipped": "Carbide", "tct": "Carbide", "hss": "High Speed Steel", "bimetal": "Bi-Metal"},
            "item_type": {"sawblade": "Saw Blade", "circular blade": "Circular Saw Blade"},
        },
        uom_rules={"dimensions": "in", "arbor_size": "in"},
        description_strategy="abrasive",
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
            "item_type": {"cutoff disc": "Cut-Off Disc", "cut off disc": "Cut-Off Disc", "cut-off wheel": "Cut-Off Wheel"},
            "material": {"alum oxide": "Aluminum Oxide", "alox": "Aluminum Oxide", "zirconia": "Zirconia Alumina"},
        },
        uom_rules={"dimensions": "in", "thickness": "in", "arbor_size": "in"},
        description_strategy="abrasive",
    ),
    "General Commercial": CategorySchema(
        name="General Commercial",
        allowed_attributes={"brand", "item_type", "mpn", "voltage", "dimensions", "mounting", "material"},
        required_attributes={"brand", "item_type", "mpn"},
        allowed_lovs={
            "mounting": {"Built-In", "Freestanding", "Leg", "Wall Mount", "Surface Mount", "Deck Mount"},
            "material": {"Stainless Steel", "Aluminum", "Carbon Steel", "Carbide", "Plastic", "Brass", "Bronze"},
            "voltage": {"120 V", "240 V", "120/240 V", "480 V", "12 V", "18 V", "20 V"},
        },
        synonym_mappings={
            "material": {"ss": "Stainless Steel", "sst": "Stainless Steel", "alum": "Aluminum"},
            "mounting": {"builtin": "Built-In", "built in": "Built-In", "freestanding": "Freestanding"},
            "voltage": {"120v": "120 V", "240v": "240 V"},
        },
        uom_rules={"voltage": "V", "amperage": "A", "dimensions": "in"},
        description_strategy="standard",
    ),
}


class CategoryDetector:
    """Deterministic category classifier based on keyword patterns, MPN structure, and taxonomies."""

    @staticmethod
    def detect(raw_desc: str, mpn: Optional[str] = None, manufacturer: Optional[str] = None) -> CategorySchema:
        text = f"{raw_desc} {mpn or ''} {manufacturer or ''}".lower()

        # 1. Appliances
        if re.search(r"\b(dishwasher|dish\s*washer)\b", text, re.IGNORECASE):
            return CATEGORY_SCHEMAS["Dishwasher"]
        if re.search(r"\b(refrigerator|fridge|range|oven|washing\s*machine|washer|dryer|water\s*heater)\b", text, re.IGNORECASE):
            return CATEGORY_SCHEMAS["Appliances"]

        # 2. Faucets
        if re.search(r"\b(faucet|pre-rinse|prerinse|spout|lavatory\s*faucet|kitchen\s*faucet)\b", text, re.IGNORECASE):
            return CATEGORY_SCHEMAS["Faucets"]

        # 3. Fittings
        if re.search(r"\b(pipe\s*fitting|tube\s*fitting|elbow|tee|coupling|adapter|union|nipple|bushing|reducer|flange|npt|mnpt|fnpt)\b", text, re.IGNORECASE):
            return CATEGORY_SCHEMAS["Fittings"]

        # 4. Abrasives & Cutting Tools
        if re.search(r"\b(cut-off|cutoff|cut\s*off|sanding\s*belt|abrasive\s*disc|grinding\s*wheel|saw\s*blade|blade|disc|stikit|abranet|cubitron|hiolit|flap\s*disc)\b", text, re.IGNORECASE):
            return CATEGORY_SCHEMAS["Abrasives/Cutting Tools"]

        return CATEGORY_SCHEMAS["General Commercial"]


category_detector = CategoryDetector()
