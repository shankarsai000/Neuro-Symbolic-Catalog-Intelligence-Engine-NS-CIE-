"""
Fixed 50-Slot Attribute Mapper (NS-CIE v2.1 Fidelity Engine)
Assigns extracted attributes to stable slots 1..15 (category canonical) and 16..50 (overflow),
preventing slot shifting when intermediate attributes are missing.
"""

from typing import Dict, List, Any

# Authoritative Canonical Slot Labels per Category (Slots 1..15)
CATEGORY_CANONICAL_SLOTS: Dict[str, List[str]] = {
    "DISHWASHER": [
        "Series",                    # Slot 1
        "Model",                     # Slot 2
        "Number of Wash Cycles",    # Slot 3
        "Voltage Rating",            # Slot 4
        "Amperage Rating",           # Slot 5
        "Mounting Type",             # Slot 6
        "Plug Type",                 # Slot 7
        "Size",                      # Slot 8
        "Depth With Door Open",      # Slot 9
        "Minimum Height",            # Slot 10
        "Maximum Height",            # Slot 11
        "Sound Level",               # Slot 12
        "Material",                  # Slot 13
        "Color",                     # Slot 14
        "Additional Information"     # Slot 15
    ],
    "POWER_TOOL": [
        "Series", "Model", "Voltage Rating", "Battery Capacity",
        "Motor Type", "Chuck Size", "No Load RPM", "Max Torque",
        "Amperage Rating", "Power Source", "Tool Length", "Tool Weight",
        "Width", "Height", "Additional Information"
    ],
    "GENERAL": [
        "Series", "Model", "Type", "Material", "Color",
        "Voltage Rating", "Amperage Rating", "Power Rating", "Capacity", "Size",
        "Length", "Width", "Height", "Weight", "Additional Information"
    ]
}

def map_attributes_to_50_slots(
    category: str,
    attributes: List[Dict[str, Any]]
) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for i in range(1, 51):
        result[f"ATTRIBUTE_LABEL {i}"] = ""
        result[f"ATTRIBUTE_VALUE {i}"] = ""
        result[f"ATTRIBUTE_UOM {i}"] = ""

    cat_upper = str(category or "").upper()
    if "DISHWASHER" in cat_upper:
        canonical_labels = CATEGORY_CANONICAL_SLOTS["DISHWASHER"]
    elif "TOOL" in cat_upper:
        canonical_labels = CATEGORY_CANONICAL_SLOTS["POWER_TOOL"]
    else:
        canonical_labels = CATEGORY_CANONICAL_SLOTS["GENERAL"]

    attr_map: Dict[str, Dict[str, Any]] = {}
    overflow_attrs: List[Dict[str, Any]] = []

    for attr in attributes:
        label = attr.get("canonical_label") or attr.get("label") or ""
        if not label:
            continue
        matched = False
        for canon_name in canonical_labels:
            if canon_name.lower() == label.lower():
                attr_map[canon_name] = attr
                matched = True
                break
        if not matched:
            overflow_attrs.append(attr)

    # Populate Slots 1..15 (Canonical category slots)
    for idx, slot_label in enumerate(canonical_labels[:15], start=1):
        result[f"ATTRIBUTE_LABEL {idx}"] = slot_label
        if slot_label in attr_map:
            item = attr_map[slot_label]
            result[f"ATTRIBUTE_VALUE {idx}"] = str(item.get("normalized_value") or item.get("value") or "")
            result[f"ATTRIBUTE_UOM {idx}"] = str(item.get("uom") or "")

    # Populate Slots 16..50 (Overflow attributes)
    for idx, item in enumerate(overflow_attrs[:35], start=16):
        label = item.get("canonical_label") or item.get("label") or f"Attribute_{idx}"
        result[f"ATTRIBUTE_LABEL {idx}"] = str(label)
        result[f"ATTRIBUTE_VALUE {idx}"] = str(item.get("normalized_value") or item.get("value") or "")
        result[f"ATTRIBUTE_UOM {idx}"] = str(item.get("uom") or "")

    return result
