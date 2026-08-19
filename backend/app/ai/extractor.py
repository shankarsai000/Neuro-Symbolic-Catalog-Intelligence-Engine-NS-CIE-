from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from app.ai.nvidia_client import NVIDIAClient, nvidia_client
from app.ai.schemas import ExtractedAttributes
from app.core.config import settings
from app.data.master_repository import master_data_repository

logger = logging.getLogger(__name__)


def _build_extraction_prompt(
    raw_desc: str,
    manufacturer: Optional[str] = None,
    category: Optional[str] = None,
    allowed_lovs: Optional[list[str]] = None,
    manufacturer_evidence: Optional[str] = None,
    mpn: Optional[str] = None,
) -> list[dict[str, str]]:
    """Construct category-specialized structured prompt adhering to Unilog catalog extraction and LOV rules."""
    allowed_item_types = ", ".join(allowed_lovs or master_data_repository.get_allowed_lovs("item_type")[:15])
    allowed_materials = ", ".join(master_data_repository.get_allowed_lovs("material")[:10])
    allowed_mountings = ", ".join(master_data_repository.get_allowed_lovs("mounting")[:8])

    category_instructions = ""
    if category == "Faucets":
        category_instructions = """
CATEGORY-SPECIFIC INSTRUCTIONS (FAUCETS):
- Extract Flow Rate in standard GPM (e.g. 1.5 GPM, 1.8 GPM).
- Extract Mounting Type (Deck Mount, Wall Mount, Centerset, Widespread, Single Hole).
- Extract Finish (Chrome, Brushed Nickel, Matte Black, Stainless Steel).
- Extract Spout Reach and Connection Size if present.
"""
    elif category == "Fittings":
        category_instructions = """
CATEGORY-SPECIFIC INSTRUCTIONS (FITTINGS):
- Extract Connection Type (NPT, MNPT, FNPT, Compression, Socket Weld, Flanged, Press, Soldered).
- Extract Connection Size (e.g. 1/2 in, 3/4 in, 2 in).
- Extract Pressure Rating in standard PSI or LB (e.g. 150 PSI, 300 LB).
- Extract Material (Brass, Stainless Steel, Copper, Cast Iron, PVC).
"""
    elif category in ["Abrasives/Cutting Tools", "Cut-Off Disc", "Saw Blade"]:
        category_instructions = """
CATEGORY-SPECIFIC INSTRUCTIONS (ABRASIVES & CUTTING TOOLS):
- Extract Dimensions (Outer Diameter x Thickness x Arbor Size).
- Extract Grit rating (e.g. P80, P120, P150).
- Extract Arbor Size (e.g. 7/8 in, 5/8 in, 20 mm).
- Extract Abrasive Material (Aluminum Oxide, Ceramic, Zirconia Alumina, Carbide).
"""
    elif category in ["Appliances", "Dishwasher"]:
        category_instructions = """
CATEGORY-SPECIFIC INSTRUCTIONS (APPLIANCES):
- Extract Voltage in standard V (e.g. 120 V, 240 V).
- Extract Amperage in standard A (e.g. 10 A, 15 A).
- Extract Sound Level in standard dBA (e.g. 41 dBA, 47 dBA).
- Extract Mounting Type (Built-In, Freestanding, Leg, Undercounter).
"""

    system_content = f"""You are the core extraction engine of the Neuro-Symbolic Catalog Intelligence Engine (NS-CIE).
Your task is to extract structured, commercial-grade product specifications from messy distributor catalog strings.

RULES & CONSTRAINTS:
1. Canonical Brand: Ground the brand to official manufacturer entities.
2. Standard Item Types: Categorize into standard taxonomies (e.g. {allowed_item_types}).
3. Standard Materials: Use standard terms (e.g. {allowed_materials}).
4. Standard Mountings: Use standard terms (e.g. {allowed_mountings}).
5. Preserve technical ratings (Voltage, Dimensions, Amperage, Grit, Flow Rate, Pressure, Pack Quantity).{category_instructions}
6. Output MUST be strictly valid JSON matching the schema below with no markdown formatting or markdown code blocks:

SCHEMA:
{{
  "brand": string or null,
  "item_type": string or null,
  "mpn": string or null,
  "voltage": string or null,
  "dimensions": string or null,
  "mounting": string or null,
  "material": string or null,
  "raw_specs": {{ "additional_key": "value" }}
}}"""

    user_content_lines = [f"Raw Catalog Description: {raw_desc}"]
    if mpn:
        user_content_lines.append(f"Manufacturer Part Number (MPN): {mpn}")
    if manufacturer:
        user_content_lines.append(f"Supplier / Manufacturer: {manufacturer}")
    if category:
        user_content_lines.append(f"Catalog Category: {category}")
    if manufacturer_evidence:
        user_content_lines.append(f"Official Manufacturer Datasheet Evidence:\n{manufacturer_evidence[:1200]}")

    user_content = "\n".join(user_content_lines)

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def _extract_heuristic_fallback(
    raw_desc: str,
    manufacturer: Optional[str] = None,
    mpn: Optional[str] = None,
    category: Optional[str] = None,
) -> ExtractedAttributes:
    """Deterministic, pure-Python category-aware heuristic extractor for offline environments."""
    text = raw_desc or ""
    raw_specs: dict[str, Any] = {}

    # 1. Voltage pattern: e.g. 120v, 120 V, 240v
    voltage_match = re.search(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:v(?:olts?)?)\b", text, re.IGNORECASE)
    voltage = f"{voltage_match.group(1)} V" if voltage_match else None

    # 2. Dimensions pattern: require dimensional unit (in, ", ', ft, mm, cm) OR multi-dimension (x)
    dim_match = re.search(
        r"\b((?:\d+[- ])?\d+(?:/\d+)?(?:\.\d+)?\s*(?:in(?:ch(?:es)?)?|\"|\'|ft|mm|cm)(?:\s*[xX]\s*(?:\d+[- ])?\d+(?:/\d+)?(?:\.\d+)?\s*(?:in(?:ch(?:es)?)?|\"|\'|ft|mm|cm)?)*)\b",
        text,
        re.IGNORECASE,
    )
    if not dim_match:
        dim_match = re.search(
            r"\b(\d+(?:[-/]\d+)?(?:\.\d+)?\s*[xX]\s*\d+(?:[-/]\d+)?(?:\.\d+)?(?:\s*[xX]\s*\d+(?:[-/]\d+)?(?:\.\d+)?)?)\b",
            text,
            re.IGNORECASE,
        )
    dimensions = dim_match.group(1).strip() if dim_match else None
    if dimensions:
        from app.core.guardrails import enforce_uom_spacing
        dimensions = enforce_uom_spacing(dimensions)

    # 3. Material pattern
    material = None
    if re.search(r"\b(?:SS|Stainless(?:\s*Steel)?|SST)\b", text, re.IGNORECASE):
        material = "Stainless Steel"
    elif re.search(r"\b(?:Chrome(?:\s*Plated)?\s*Brass)\b", text, re.IGNORECASE):
        material = "Chrome Plated Brass"
    elif re.search(r"\b(?:Solid\s*Brass|Brass)\b", text, re.IGNORECASE):
        material = "Brass"
    elif re.search(r"\b(?:Copper)\b", text, re.IGNORECASE):
        material = "Copper"
    elif re.search(r"\b(?:Cast\s*Iron)\b", text, re.IGNORECASE):
        material = "Cast Iron"
    elif re.search(r"\b(?:Ductile\s*Iron)\b", text, re.IGNORECASE):
        material = "Ductile Iron"
    elif re.search(r"\b(?:Aluminum|Alum)\b", text, re.IGNORECASE):
        material = "Aluminum"
    elif re.search(r"\b(?:Aluminum\s*Oxide|Alox)\b", text, re.IGNORECASE):
        material = "Aluminum Oxide"
    elif re.search(r"\b(?:Zirconia(?:\s*Alumina)?)\b", text, re.IGNORECASE):
        material = "Zirconia Alumina"
    elif re.search(r"\b(?:Carbide(?:\s*Tipped)?)\b", text, re.IGNORECASE):
        material = "Carbide"
    elif re.search(r"\b(?:Carbon(?:\s*Steel)?|Metal)\b", text, re.IGNORECASE):
        material = "Carbon Steel"

    # 4. Mounting pattern
    mounting = None
    if re.search(r"\bBuilt[- ]?in\b", text, re.IGNORECASE):
        mounting = "Built-In"
    elif re.search(r"\bDeck[- ]?Mount(?:ed)?\b", text, re.IGNORECASE):
        mounting = "Deck Mount"
    elif re.search(r"\bWall[- ]?Mount(?:ed)?\b", text, re.IGNORECASE):
        mounting = "Wall Mount"
    elif re.search(r"\bCenterset\b", text, re.IGNORECASE):
        mounting = "Centerset"
    elif re.search(r"\bWidespread\b", text, re.IGNORECASE):
        mounting = "Widespread"
    elif re.search(r"\bSingle[- ]?Hole\b", text, re.IGNORECASE):
        mounting = "Single Hole"
    elif re.search(r"\bFreestanding\b", text, re.IGNORECASE):
        mounting = "Freestanding"
    elif re.search(r"\bLeg\b", text, re.IGNORECASE):
        mounting = "Leg"

    # 5. Item Type classification (Category-Aware)
    item_type = None
    # A. Faucets
    if re.search(r"\bPre[- ]?Rinse(?:\s*Faucet)?\b", text, re.IGNORECASE):
        item_type = "Pre-Rinse Faucet"
    elif re.search(r"\bKitchen\s*Faucet\b", text, re.IGNORECASE):
        item_type = "Kitchen Faucet"
    elif re.search(r"\bLavatory\s*Faucet|Lav\s*Faucet\b", text, re.IGNORECASE):
        item_type = "Lavatory Faucet"
    elif re.search(r"\bCommercial\s*Faucet\b", text, re.IGNORECASE):
        item_type = "Commercial Faucet"
    elif re.search(r"\bFaucet\b", text, re.IGNORECASE):
        item_type = "Faucet"

    # B. Fittings
    elif re.search(r"\b(?:90|45)?\s*Elbow\b", text, re.IGNORECASE):
        item_type = "Elbow"
    elif re.search(r"\bTee\b", text, re.IGNORECASE):
        item_type = "Tee"
    elif re.search(r"\bCoupling\b", text, re.IGNORECASE):
        item_type = "Coupling"
    elif re.search(r"\bAdapter\b", text, re.IGNORECASE):
        item_type = "Adapter"
    elif re.search(r"\bUnion\b", text, re.IGNORECASE):
        item_type = "Union"
    elif re.search(r"\bPipe\s*Fitting\b", text, re.IGNORECASE):
        item_type = "Pipe Fitting"
    elif re.search(r"\bFlange\b", text, re.IGNORECASE):
        item_type = "Flange"

    # C. Abrasives / Cutting Tools
    elif re.search(r"\bCut[- ]?Off\s*(?:Disc|Wheel)\b", text, re.IGNORECASE):
        item_type = "Cut-Off Disc"
    elif re.search(r"\bSanding\s*Belt\b", text, re.IGNORECASE):
        item_type = "Sanding Belt"
    elif re.search(r"\bAbrasive\s*Disc|Stikit|Abranet|Hiolit\b", text, re.IGNORECASE):
        item_type = "Abrasive Disc"
    elif re.search(r"\bGrinding\s*Wheel\b", text, re.IGNORECASE):
        item_type = "Grinding Wheel"
    elif re.search(r"\bSaw\s*Blade|Blade\b", text, re.IGNORECASE):
        item_type = "Saw Blade"
    elif re.search(r"\bDrill\s*Bit|Bit\b", text, re.IGNORECASE):
        item_type = "Drill Bit"

    # D. Appliances
    elif re.search(r"\bDishwasher\b", text, re.IGNORECASE):
        item_type = "Dishwasher"
    elif re.search(r"\bRefrigerator\b", text, re.IGNORECASE):
        item_type = "Refrigerator"
    elif re.search(r"\bRange|Oven\b", text, re.IGNORECASE):
        item_type = "Range"
    elif re.search(r"\bWashing\s*Machine|Washer\b", text, re.IGNORECASE):
        item_type = "Washing Machine"
    elif re.search(r"\bDryer\b", text, re.IGNORECASE):
        item_type = "Dryer"

    # 6. Specialized Category-Specific Attribute Regexes
    # A. Flow Rate (GPM) for Faucets
    gpm_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:gpm|gal/min)\b", text, re.IGNORECASE)
    if gpm_match:
        raw_specs["FlowRate"] = f"{gpm_match.group(1)} GPM"

    # B. Connection Type for Fittings
    if re.search(r"\b(MNPT|FNPT|NPT)\b", text, re.IGNORECASE):
        raw_specs["ConnectionType"] = re.search(r"\b(MNPT|FNPT|NPT)\b", text, re.IGNORECASE).group(1).upper()
    elif re.search(r"\b(Compression|Socket Weld|Push-to-Connect|Press|Flanged|Soldered|Threaded)\b", text, re.IGNORECASE):
        raw_specs["ConnectionType"] = re.search(r"\b(Compression|Socket Weld|Push-to-Connect|Press|Flanged|Soldered|Threaded)\b", text, re.IGNORECASE).group(1).title()

    # C. Pressure Rating for Fittings
    psi_match = re.search(r"\b(\d+)\s*(?:psi|psig)\b", text, re.IGNORECASE)
    if psi_match:
        raw_specs["PressureRating"] = f"{psi_match.group(1)} PSI"
    else:
        lb_match = re.search(r"\b(\d+)\s*(?:lb|#)\b", text, re.IGNORECASE)
        if lb_match:
            raw_specs["PressureRating"] = f"{lb_match.group(1)} LB"

    # D. Grit for Abrasives
    grit_match = re.search(r"\b(?:P|p-?)(\d{2,4})\b|\b(\d{2,4})\s*(?:Grit|grit)\b", text)
    if grit_match:
        g_val = grit_match.group(1) or grit_match.group(2)
        raw_specs["Grit"] = f"P{g_val}"

    # E. Arbor Size for Abrasives
    arbor_match = re.search(r"[xX]\s*(\d+(?:/\d+)?(?:\.\d+)?\s*(?:in|\"|mm)?)\s*(?:arbor|hole|disc|wheel)?\b", text, re.IGNORECASE)
    if arbor_match and dimensions and arbor_match.group(1) not in dimensions:
        raw_specs["ArborSize"] = arbor_match.group(1).replace('"', ' in').strip()

    # F. Finish for Faucets
    if re.search(r"\b(?:Polished\s*Chrome|Chrome|CP)\b", text, re.IGNORECASE):
        raw_specs["Finish"] = "Chrome"
    elif re.search(r"\b(?:Brushed\s*Nickel|BN)\b", text, re.IGNORECASE):
        raw_specs["Finish"] = "Brushed Nickel"
    elif re.search(r"\b(?:Matte\s*Black|MB)\b", text, re.IGNORECASE):
        raw_specs["Finish"] = "Matte Black"

    # G. Amperage / Sound Level / Pack Quantity for Appliances & Tools
    amp_match = re.search(r"\b(\d+)\s*(?:a|amps?|amperage)\b", text, re.IGNORECASE)
    if amp_match:
        raw_specs["Amperage"] = f"{amp_match.group(1)} A"

    dba_match = re.search(r"\b(\d+)\s*(?:dba|db)\b", text, re.IGNORECASE)
    if dba_match:
        raw_specs["SoundLevel"] = f"{dba_match.group(1)} dBA"

    pack_match = re.search(r"\b(\d+)\s*(?:pc|pack|pk|disc/box)\b", text, re.IGNORECASE)
    if pack_match:
        raw_specs["PackQuantity"] = f"{pack_match.group(1)} PK"

    # 7. MPN extraction fallback
    if not mpn:
        mpn_match = re.match(r"^([A-Z0-9\-]+)", text.strip())
        mpn = mpn_match.group(1) if mpn_match else None

    return ExtractedAttributes(
        brand=manufacturer,
        item_type=item_type,
        mpn=mpn,
        voltage=voltage,
        dimensions=dimensions,
        mounting=mounting,
        material=material,
        raw_specs=raw_specs,
    )


class StructuredExtractor:
    """Production structured extractor wrapping NVIDIA NIM with Pydantic validation."""

    def __init__(self, client: Optional[NVIDIAClient] = None) -> None:
        self.client = client or nvidia_client

    def extract(
        self,
        raw_desc: str,
        manufacturer: Optional[str] = None,
        category: Optional[str] = None,
        allowed_lovs: Optional[list[str]] = None,
        manufacturer_evidence: Optional[Any] = None,
        mpn: Optional[str] = None,
    ) -> tuple[ExtractedAttributes, str]:
        """Extract structured attributes using Evidence-First architecture."""
        from app.core.technical_extractor import technical_spec_extractor

        # Step 1: Run Evidence-First Deterministic Spec Extractor
        evidence_dict = manufacturer_evidence if isinstance(manufacturer_evidence, dict) else (
            manufacturer_evidence.to_dict() if hasattr(manufacturer_evidence, "to_dict") else {}
        )
        tech_specs = technical_spec_extractor.extract_specs(
            raw_desc=raw_desc,
            category=category,
            manufacturer_evidence=evidence_dict,
            mpn=mpn,
            brand=manufacturer,
        )

        ev_text = ""
        if isinstance(manufacturer_evidence, str):
            ev_text = manufacturer_evidence
        elif isinstance(evidence_dict, dict) and evidence_dict.get("extracted_text"):
            ev_text = evidence_dict["extracted_text"]

        if self.client.is_configured():
            try:
                messages = _build_extraction_prompt(
                    raw_desc=raw_desc,
                    manufacturer=manufacturer,
                    category=category,
                    allowed_lovs=allowed_lovs,
                    manufacturer_evidence=ev_text,
                    mpn=mpn,
                )

                content, _ = self.client.generate_chat_completion(
                    messages=messages,
                    temperature=0.0,
                    max_tokens=1024,
                )

                # Strip markdown code fences if present (e.g. ```json ... ```)
                json_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", content)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    json_match2 = re.search(r"(\{[\s\S]*\})", content)
                    json_str = json_match2.group(1) if json_match2 else content.strip()

                parsed_data = json.loads(json_str)

                # Evidence-First Priority: Preserved deterministic manufacturer evidence values take precedence
                if tech_specs.get("brand"):
                    parsed_data["brand"] = tech_specs["brand"]
                if tech_specs.get("mpn"):
                    parsed_data["mpn"] = tech_specs["mpn"]
                if tech_specs.get("voltage"):
                    parsed_data["voltage"] = tech_specs["voltage"]
                if tech_specs.get("amperage"):
                    parsed_data["amperage"] = tech_specs["amperage"]
                if tech_specs.get("dimensions"):
                    parsed_data["dimensions"] = tech_specs["dimensions"]
                if tech_specs.get("mounting"):
                    parsed_data["mounting"] = tech_specs["mounting"]
                if tech_specs.get("material"):
                    parsed_data["material"] = tech_specs["material"]
                if tech_specs.get("item_type"):
                    parsed_data["item_type"] = tech_specs["item_type"]

                raw_specs = parsed_data.get("raw_specs", {})
                if tech_specs.get("raw_specs"):
                    raw_specs.update(tech_specs["raw_specs"])
                parsed_data["raw_specs"] = raw_specs

                extracted = ExtractedAttributes(**parsed_data)
                return extracted, "LIVE_NIM"

            except Exception as e:
                logger.warning(f"Live NVIDIA NIM extraction error ({e})")
                if settings.require_live_nim:
                    raise RuntimeError(f"Live NVIDIA NIM required but failed: {e}")

        # Deterministic offline heuristic fallback with evidence integration
        fallback = _extract_heuristic_fallback(raw_desc, manufacturer, mpn, category)

        # Priority 1: Merge verified technical specs into fallback
        res_brand = tech_specs.get("brand") or fallback.brand or manufacturer
        res_mpn = tech_specs.get("mpn") or fallback.mpn or mpn
        res_type = tech_specs.get("item_type") or fallback.item_type
        res_volt = tech_specs.get("voltage") or fallback.voltage
        res_dim = tech_specs.get("dimensions") or fallback.dimensions
        res_moun = tech_specs.get("mounting") or fallback.mounting
        res_mat = tech_specs.get("material") or fallback.material

        merged_raw_specs = dict(fallback.raw_specs or {})
        if tech_specs.get("raw_specs"):
            merged_raw_specs.update(tech_specs["raw_specs"])

        res_attributes = ExtractedAttributes(
            brand=res_brand,
            item_type=res_type,
            mpn=res_mpn,
            voltage=res_volt,
            dimensions=res_dim,
            mounting=res_moun,
            material=res_mat,
            raw_specs=merged_raw_specs,
        )
        return res_attributes, "OFFLINE_HEURISTIC"


structured_extractor = StructuredExtractor()


def extract_product_specs(
    raw_desc: str,
    manufacturer: Optional[str] = None,
    manufacturer_evidence: Optional[str] = None,
    category: Optional[str] = None,
    allowed_lovs: Optional[list[str]] = None,
    mpn: Optional[str] = None,
) -> tuple[ExtractedAttributes, str]:
    """Top-level functional interface routing extraction through StructuredExtractor."""
    return structured_extractor.extract(
        raw_desc=raw_desc,
        manufacturer=manufacturer,
        category=category,
        allowed_lovs=allowed_lovs,
        manufacturer_evidence=manufacturer_evidence,
        mpn=mpn,
    )
