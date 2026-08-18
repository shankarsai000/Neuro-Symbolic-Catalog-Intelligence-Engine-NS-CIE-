from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from openai import OpenAI

from app.ai.schemas import ExtractedAttributes
from app.core.config import settings

logger = logging.getLogger(__name__)

# Heuristic patterns for robust fallback extraction
VOLTAGE_REGEX = re.compile(r"\b(\d+(?:\.\d+)?\s*(?:v|volts?|kv))\b", re.IGNORECASE)
DIMENSION_REGEX = re.compile(
    r"\b(\d+(?:-\d+/\d+|\.\d+|/\d+)?\s*(?:in|inch(?:es)?|\"|ft|mm|cm|m|x|\'|by)\s*(?:\d+(?:-\d+/\d+|\.\d+|/\d+)?\s*(?:in|inch(?:es)?|\"|ft|mm|cm|m|\')*)?)\b",
    re.IGNORECASE,
)
MATERIAL_REGEX = re.compile(
    r"\b(stainless\s+steel|sst|ss|aluminum|brass|steel|copper|plastic|cast\s+iron|pvc|rubber|ceramic)\b",
    re.IGNORECASE,
)
MOUNTING_REGEX = re.compile(
    r"\b(leg|built-in|wall|ceiling|flush|surface|din\s*rail|freestanding)\s*(?:mount(?:ing)?)?\b",
    re.IGNORECASE,
)
ITEM_TYPE_REGEX = re.compile(
    r"\b(dishwasher|cut-off\s+disc|sanding\s+belt|disc|belt|blade|motor|pump|valve|switch|breaker|socket|drill|saw|sensor|filter|refrigerator|range|oven)\b",
    re.IGNORECASE,
)


def _heuristic_fallback_extract(
    raw_desc: str,
    manufacturer: Optional[str] = None,
    manufacturer_context: Optional[str] = None,
) -> ExtractedAttributes:
    """Fast deterministic rule-based extractor when LLM is unavailable."""
    combined_text = f"{raw_desc} {manufacturer_context or ''}"

    brand = manufacturer.strip() if manufacturer else None

    # Item Type
    item_type_match = ITEM_TYPE_REGEX.search(combined_text)
    item_type = item_type_match.group(1).title() if item_type_match else None

    # Voltage
    volt_match = VOLTAGE_REGEX.search(combined_text)
    voltage = volt_match.group(1) if volt_match else None

    # Material
    mat_match = MATERIAL_REGEX.search(combined_text)
    material = mat_match.group(1).title() if mat_match else None
    if material and material.lower() in ("ss", "sst"):
        material = "Stainless Steel"

    # Mounting
    mount_match = MOUNTING_REGEX.search(combined_text)
    mounting = mount_match.group(1).title() if mount_match else None

    # Dimensions
    dim_match = DIMENSION_REGEX.search(raw_desc) or DIMENSION_REGEX.search(combined_text)
    dimensions = dim_match.group(1) if dim_match else None

    # Part number extraction
    tokens = raw_desc.split()
    mpn = tokens[0] if tokens and any(char.isdigit() for char in tokens[0]) else None

    return ExtractedAttributes(
        brand=brand,
        item_type=item_type,
        mpn=mpn,
        voltage=voltage,
        dimensions=dimensions,
        mounting=mounting,
        material=material,
        raw_specs={},
    )


def extract_product_specs(
    raw_desc: str,
    manufacturer: Optional[str] = None,
    manufacturer_context: Optional[str] = None,
) -> tuple[ExtractedAttributes, float, str]:
    """Extract structured technical product parameters from unstructured catalog text.

    Args:
        raw_desc: Cleaned or raw catalog description string.
        manufacturer: Optional manufacturer or supplier name.
        manufacturer_context: Optional scraped datasheet context to ground extraction.

    Returns:
        tuple of (ExtractedAttributes, confidence_score, status_message)
    """
    if not raw_desc or not raw_desc.strip():
        return ExtractedAttributes(), 0.0, "empty_input"

    # If dummy API key is configured or offline, use heuristic extractor directly
    is_dummy_key = (
        not settings.llm_api_key
        or "dummy" in settings.llm_api_key.lower()
        or settings.llm_api_key == "dummy_key_if_missing"
    )

    if is_dummy_key:
        extracted = _heuristic_fallback_extract(
            raw_desc=raw_desc,
            manufacturer=manufacturer,
            manufacturer_context=manufacturer_context,
        )
        return extracted, 0.85, "heuristic_fallback"

    system_prompt = (
        "You are an industrial catalog specialist for the NS-CIE extraction engine. "
        "Extract structured technical parameters from the product description and manufacturer datasheet into JSON. "
        "Ground your extraction strictly on the provided text without hallucinating facts. "
        "Return ONLY a valid JSON object matching the exact schema without explanations, markdown headers, or chatter:\n"
        "{\n"
        '  "brand": string or null,\n'
        '  "item_type": string or null,\n'
        '  "mpn": string or null,\n'
        '  "voltage": string or null,\n'
        '  "dimensions": string or null,\n'
        '  "mounting": string or null,\n'
        '  "material": string or null,\n'
        '  "raw_specs": {}\n'
        "}"
    )

    user_prompt = f"Product Description: {raw_desc}"
    if manufacturer:
        user_prompt += f"\nCanonical Brand: {manufacturer}"
    if manufacturer_context:
        user_prompt += f"\nManufacturer Datasheet Grounding Context:\n{manufacturer_context[:1000]}"

    try:
        client = OpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            timeout=15.0,
        )

        response = client.chat.completions.create(
            model=settings.llm_model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            response_format={"type": "json_object"}
            if "integrate.api.nvidia.com" in settings.llm_base_url
            else None,
        )

        content = response.choices[0].message.content or ""
        content_clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
        parsed_json = json.loads(content_clean)

        attributes = ExtractedAttributes(
            brand=parsed_json.get("brand") or manufacturer,
            item_type=parsed_json.get("item_type"),
            mpn=parsed_json.get("mpn"),
            voltage=parsed_json.get("voltage"),
            dimensions=parsed_json.get("dimensions"),
            mounting=parsed_json.get("mounting"),
            material=parsed_json.get("material"),
            raw_specs=parsed_json.get("raw_specs") or {},
        )
        return attributes, 0.98, "llm_extracted"

    except Exception as e:
        logger.warning(
            f"LLM extraction failed ({e}); switching to deterministic heuristic fallback"
        )
        fallback = _heuristic_fallback_extract(
            raw_desc=raw_desc,
            manufacturer=manufacturer,
            manufacturer_context=manufacturer_context,
        )
        return fallback, 0.80, f"fallback_extracted: {str(e)[:50]}"
