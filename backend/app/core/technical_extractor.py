from __future__ import annotations

import logging
import re
from typing import Any, Optional

from app.core.guardrails import enforce_uom_spacing

logger = logging.getLogger(__name__)


class TechnicalSpecificationExtractor:
    """Category-aware, label-aware deterministic technical spec extractor.

    Extracts verified, structured product attributes directly from:
    1. Official manufacturer spec_sections dictionary
    2. Official manufacturer evidence snippets / text
    3. Category-aware label & regex patterns
    """

    @staticmethod
    def extract_specs(
        raw_desc: str,
        category: Optional[str] = None,
        manufacturer_evidence: Optional[dict[str, Any]] = None,
        mpn: Optional[str] = None,
        brand: Optional[str] = None,
    ) -> dict[str, Any]:
        extracted: dict[str, Any] = {
            "brand": brand,
            "mpn": mpn,
            "item_type": None,
            "voltage": None,
            "amperage": None,
            "sound_level": None,
            "mounting": None,
            "dimensions": None,
            "material": None,
            "color": None,
            "series": None,
            "wash_cycles": None,
            "depth_door_open": None,
            "min_height": None,
            "max_height": None,
            "raw_specs": {},
            "spec_sections": {},
            "provenance": {},
        }

        # 1. Inspect Official Manufacturer Evidence
        spec_sections = {}
        snippets = {}
        source_url = ""
        source_type = "distributor_feed"

        if manufacturer_evidence:
            if isinstance(manufacturer_evidence, dict):
                spec_sections = manufacturer_evidence.get("spec_sections", {})
                snippets = manufacturer_evidence.get("evidence_snippets", {})
                source_url = manufacturer_evidence.get("source_url", "")
                source_type = manufacturer_evidence.get("source_type", "manufacturer_official_html")
            elif hasattr(manufacturer_evidence, "spec_sections"):
                spec_sections = getattr(manufacturer_evidence, "spec_sections", {})
                snippets = getattr(manufacturer_evidence, "evidence_snippets", {})
                source_url = getattr(manufacturer_evidence, "source_url", "")
                source_type = getattr(manufacturer_evidence, "source_type", "manufacturer_official_html")

        if spec_sections:
            extracted["spec_sections"] = dict(spec_sections)
            extracted["raw_specs"]["spec_sections"] = dict(spec_sections)
            for k, v in spec_sections.items():
                extracted["raw_specs"][k] = v

        # A. Series
        if "Series" in spec_sections:
            extracted["series"] = spec_sections["Series"]
            extracted["raw_specs"]["Series"] = spec_sections["Series"]

        # B. Wash Cycles
        if "Number of Wash Cycles" in spec_sections:
            c_val = str(spec_sections["Number of Wash Cycles"]).replace(".0", "")
            extracted["wash_cycles"] = c_val
            extracted["raw_specs"]["Number of Wash Cycles"] = c_val
        elif re.search(r"\b(\d+)[- ](?:wash|cycle)\b", raw_desc, re.IGNORECASE):
            m = re.search(r"\b(\d+)[- ](?:wash|cycle)\b", raw_desc, re.IGNORECASE)
            extracted["wash_cycles"] = m.group(1)

        # C. Voltage
        if "Voltage Rating" in spec_sections:
            v_val = str(spec_sections["Voltage Rating"])
            if not v_val.endswith(" V"):
                v_val = f"{v_val.replace('V', '').strip()} V"
            extracted["voltage"] = v_val
        elif "voltage" in snippets and isinstance(snippets["voltage"], dict):
            extracted["voltage"] = snippets["voltage"].get("value")
        else:
            v_match = re.search(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:v(?:olts?)?)\b", raw_desc, re.IGNORECASE)
            if v_match:
                extracted["voltage"] = f"{v_match.group(1)} V"

        # D. Amperage
        if "Amperage Rating" in spec_sections:
            a_val = str(spec_sections["Amperage Rating"])
            if not a_val.endswith(" A"):
                a_val = f"{a_val.replace('A', '').strip()} A"
            extracted["amperage"] = a_val
            extracted["raw_specs"]["Amperage"] = a_val
        elif "amperage" in snippets and isinstance(snippets["amperage"], dict):
            extracted["amperage"] = snippets["amperage"].get("value")
            extracted["raw_specs"]["Amperage"] = snippets["amperage"].get("value")
        else:
            a_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:a|amps?|amperage)\b", raw_desc, re.IGNORECASE)
            if a_match:
                extracted["amperage"] = f"{a_match.group(1)} A"
                extracted["raw_specs"]["Amperage"] = f"{a_match.group(1)} A"

        # E. Sound Level
        if "Sound Level" in spec_sections:
            s_val = str(spec_sections["Sound Level"])
            if not s_val.endswith(" dBA"):
                s_val = f"{s_val.replace('dBA', '').replace('dB', '').strip()} dBA"
            extracted["sound_level"] = s_val
            extracted["raw_specs"]["SoundLevel"] = s_val
        elif "sound_level" in snippets and isinstance(snippets["sound_level"], dict):
            extracted["sound_level"] = snippets["sound_level"].get("value")
            extracted["raw_specs"]["SoundLevel"] = snippets["sound_level"].get("value")
        else:
            dba_match = re.search(r"\b(\d+)\s*(?:dba|db)\b", raw_desc, re.IGNORECASE)
            if dba_match:
                extracted["sound_level"] = f"{dba_match.group(1)} dBA"
                extracted["raw_specs"]["SoundLevel"] = f"{dba_match.group(1)} dBA"

        # F. Mounting Type (Standardized LOV: "Built-In", "Leg", "Freestanding", etc.)
        if "Mounting Type" in spec_sections:
            m_str = spec_sections["Mounting Type"]
            extracted["mounting"] = "Built-In" if "built" in m_str.lower() else m_str
        elif "mounting" in snippets and isinstance(snippets["mounting"], dict):
            m_str = str(snippets["mounting"].get("value", ""))
            extracted["mounting"] = "Built-In" if "built" in m_str.lower() else m_str
        else:
            if re.search(r"\bBuilt[- ]?in\b", raw_desc, re.IGNORECASE):
                extracted["mounting"] = "Built-In"
            elif re.search(r"\bLeg\b", raw_desc, re.IGNORECASE):
                extracted["mounting"] = "Leg"
            elif re.search(r"\bFreestanding\b", raw_desc, re.IGNORECASE):
                extracted["mounting"] = "Freestanding"

        # G. Size / Dimensions
        if "Size" in spec_sections:
            extracted["dimensions"] = spec_sections["Size"]
        elif "Width" in spec_sections and "Depth" in spec_sections:
            extracted["dimensions"] = f"{spec_sections['Width']} W x {spec_sections['Depth']} D"
        elif "dimensions" in snippets and isinstance(snippets["dimensions"], dict):
            extracted["dimensions"] = snippets["dimensions"].get("value")
        else:
            # Full dimensional match with fractional numbers like 7-1/4 in
            dim_match = re.search(
                r"\b((?:\d+[- ])?\d+(?:/\d+)?(?:\.\d+)?\s*(?:in(?:ch(?:es)?)?|\"|\'|ft|mm|cm)(?:\s*[xX]\s*(?:\d+[- ])?\d+(?:/\d+)?(?:\.\d+)?\s*(?:in(?:ch(?:es)?)?|\"|\'|ft|mm|cm)?)*)\b",
                raw_desc,
                re.IGNORECASE,
            )
            if dim_match:
                extracted["dimensions"] = enforce_uom_spacing(dim_match.group(1).strip())

        # H. Depth With Door Open
        if "Depth With Door Open" in spec_sections:
            extracted["depth_door_open"] = spec_sections["Depth With Door Open"]
            extracted["raw_specs"]["DepthWithDoorOpen"] = spec_sections["Depth With Door Open"]

        # I. Minimum & Maximum Height
        if "Minimum Height" in spec_sections:
            extracted["min_height"] = spec_sections["Minimum Height"]
        if "Maximum Height" in spec_sections:
            extracted["max_height"] = spec_sections["Maximum Height"]

        # J. Material & Color
        if "Material" in spec_sections:
            extracted["material"] = spec_sections["Material"]
        elif re.search(r"\b(?:SS|Stainless(?:\s*Steel)?|SST)\b", raw_desc, re.IGNORECASE):
            extracted["material"] = "Stainless Steel"

        if "Color" in spec_sections:
            extracted["color"] = spec_sections["Color"]

        # K. Item Type Classification
        type_lower = (category or "").lower()
        if "dishwasher" in type_lower or "dishwasher" in raw_desc.lower():
            extracted["item_type"] = "Dishwasher"

        # Construct Provenance Records
        for key in ["brand", "item_type", "voltage", "amperage", "sound_level", "mounting", "dimensions", "material"]:
            val = extracted.get(key)
            if val:
                extracted["provenance"][key] = {
                    "value": val,
                    "source_url": source_url or "manufacturer_official",
                    "source_type": source_type if spec_sections else "distributor_feed",
                    "evidence": f"Extracted {key}: {val}",
                    "confidence": 1.0 if spec_sections else 0.85,
                    "llm_generated": False,
                }

        return extracted


technical_spec_extractor = TechnicalSpecificationExtractor()
