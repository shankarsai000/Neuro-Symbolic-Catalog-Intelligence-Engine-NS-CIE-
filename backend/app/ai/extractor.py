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
    """Construct structured prompt adhering to Unilog catalog extraction and LOV rules."""
    allowed_item_types = ", ".join(allowed_lovs or master_data_repository.get_allowed_lovs("item_type")[:15])
    allowed_materials = ", ".join(master_data_repository.get_allowed_lovs("material")[:10])
    allowed_mountings = ", ".join(master_data_repository.get_allowed_lovs("mounting")[:8])

    system_content = f"""You are the core extraction engine of the Neuro-Symbolic Catalog Intelligence Engine (NS-CIE).
Your task is to extract structured, commercial-grade product specifications from messy distributor catalog strings.

RULES & CONSTRAINTS:
1. Canonical Brand: Ground the brand to official manufacturer entities.
2. Standard Item Types: Categorize into standard taxonomies (e.g. {allowed_item_types}).
3. Standard Materials: Use standard terms (e.g. {allowed_materials}).
4. Standard Mountings: Use standard terms (e.g. {allowed_mountings}).
5. Preserve technical ratings (Voltage, Dimensions, Amperage, Grit, Pack Quantity).
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
) -> ExtractedAttributes:
    """Deterministic, pure-Python heuristic extractor for offline environments."""
    text = raw_desc or ""

    # 1. Voltage pattern: e.g. 120v, 120 V, 240v
    voltage_match = re.search(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:v(?:olts?)?)\b", text, re.IGNORECASE)
    voltage = f"{voltage_match.group(1)} V" if voltage_match else None

    # 2. Dimensions pattern: require dimensional unit (in, ", ', ft, mm, cm) OR multi-dimension (x)
    dim_match = re.search(
        r"\b(\d+(?:[-/]\d+)?(?:\.\d+)?\s*(?:in(?:ch(?:es)?)?|\"|\'|ft|mm|cm)(?:\s*[xX]\s*\d+(?:[-/]\d+)?(?:\.\d+)?\s*(?:in(?:ch(?:es)?)?|\"|\'|ft|mm|cm)?)*)\b",
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
    elif re.search(r"\b(?:Aluminum|Alum)\b", text, re.IGNORECASE):
        material = "Aluminum"
    elif re.search(r"\b(?:Carbon(?:\s*Steel)?|Metal)\b", text, re.IGNORECASE):
        material = "Carbon Steel"

    # 4. Mounting pattern
    mounting = None
    if re.search(r"\bBuilt[- ]?in\b", text, re.IGNORECASE):
        mounting = "Built-In"
    elif re.search(r"\bFreestanding\b", text, re.IGNORECASE):
        mounting = "Freestanding"
    elif re.search(r"\bLeg\b", text, re.IGNORECASE):
        mounting = "Leg"

    # 5. Item Type classification
    item_type = None
    if re.search(r"\bDishwasher\b", text, re.IGNORECASE):
        item_type = "Dishwasher"
    elif re.search(r"\bCut[- ]?Off\s*Disc\b", text, re.IGNORECASE):
        item_type = "Cut-Off Disc"
    elif re.search(r"\bSanding\s*Belt\b", text, re.IGNORECASE):
        item_type = "Sanding Belt"
    elif re.search(r"\bAbrasive\s*Disc\b", text, re.IGNORECASE):
        item_type = "Abrasive Disc"
    elif re.search(r"\bSaw\s*Blade\b", text, re.IGNORECASE):
        item_type = "Saw Blade"
    elif re.search(r"\bBlade\b", text, re.IGNORECASE):
        item_type = "Saw Blade"
    elif re.search(r"\bBit\b", text, re.IGNORECASE):
        item_type = "Drill Bit"

    # 6. Additional Specs
    raw_specs: dict[str, Any] = {}
    amp_match = re.search(r"\b(\d+)\s*(?:a|amps?|amperage)\b", text, re.IGNORECASE)
    if amp_match:
        raw_specs["Amperage"] = f"{amp_match.group(1)} A"

    dba_match = re.search(r"\b(\d+)\s*(?:dba|db)\b", text, re.IGNORECASE)
    if dba_match:
        raw_specs["SoundLevel"] = f"{dba_match.group(1)} dBA"

    pack_match = re.search(r"\b(\d+)\s*(?:pc|pack|pk)\b", text, re.IGNORECASE)
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
        manufacturer_evidence: Optional[str] = None,
        mpn: Optional[str] = None,
    ) -> tuple[ExtractedAttributes, str]:
        """Extract structured attributes using live NVIDIA NIM when configured, with explicit fallback."""
        if self.client.is_configured():
            try:
                messages = _build_extraction_prompt(
                    raw_desc=raw_desc,
                    manufacturer=manufacturer,
                    category=category,
                    allowed_lovs=allowed_lovs,
                    manufacturer_evidence=manufacturer_evidence,
                    mpn=mpn,
                )

                content, _ = self.client.generate_chat_completion(
                    messages=messages,
                    temperature=0.0,
                    max_tokens=600,
                )

                # Strip markdown code fences if present (e.g. ```json ... ```)
                cleaned = re.sub(r"^```(?:json)?\s*", "", content.strip(), flags=re.MULTILINE)
                cleaned = re.sub(r"```$", "", cleaned.strip(), flags=re.MULTILINE)

                parsed_data = json.loads(cleaned)
                extracted = ExtractedAttributes(**parsed_data)
                return extracted, "LIVE_NIM"

            except Exception as e:
                logger.warning(f"Live NVIDIA NIM extraction error ({e})")
                if settings.require_live_nim:
                    raise RuntimeError(f"Live NVIDIA NIM required but failed: {e}")

        # Deterministic offline heuristic fallback
        fallback = _extract_heuristic_fallback(raw_desc, manufacturer, mpn)
        return fallback, "OFFLINE_HEURISTIC"


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
