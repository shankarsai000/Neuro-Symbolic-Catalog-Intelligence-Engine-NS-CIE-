"""
Generic Description & Feature Synthesis Engine (NS-CIE v2.1 Fidelity Engine)
Generates channel descriptions purely from canonical facts.
Zero product-specific hardcoding.
"""

from typing import Dict, Any, Optional, List

def generate_channel_descriptions(
    mpn: Optional[str],
    oem_name: Optional[str],
    brand_name: Optional[str],
    product_name: Optional[str],
    series: Optional[str] = None,
    with_feature: Optional[str] = None,
    mounting_type: Optional[str] = None,
    cycles: Optional[str] = None,
    voltage: Optional[str] = None,
    amperage: Optional[str] = None,
    size: Optional[str] = None,
    depth_door_open: Optional[str] = None,
    min_height: Optional[str] = None,
    max_height: Optional[str] = None,
    sound_level: Optional[str] = None,
    material: Optional[str] = None,
    color: Optional[str] = None,
    additional_info: Optional[str] = None,
    marketing_evidence: Optional[str] = None
) -> Dict[str, str]:
    mpn_str = str(mpn or "").strip()
    brand_str = str(brand_name or oem_name or "Unbranded").strip()
    title_str = str(product_name or "Product").strip()
    series_str = str(series or "").strip()

    # 1. MOBILE_DESC
    mobile_parts = [brand_str, title_str]
    if series_str:
        mobile_parts.append(series_str)
    mobile_parts.append(mpn_str)
    if mounting_type:
        mobile_parts.append(f"{mounting_type} Mounting")
    mobile_desc = ", ".join(p for p in mobile_parts if p)[:80]

    # 2. INVOICE_DESC (Max ~40 chars, upper)
    mount_abbr = "BLTLN" if mounting_type and "built" in mounting_type.lower() else (mounting_type.upper() if mounting_type else "")
    mat_abbr = "SST" if material and "stainless" in material.lower() else ""
    volt_str = f"{voltage}V" if voltage else ""
    amp_str = f"{amperage}A" if amperage else ""
    sound_str = f"{sound_level}DBA" if sound_level else ""
    invoice_parts = [title_str.upper(), mount_abbr, mat_abbr, mat_abbr, volt_str, amp_str, sound_str]
    invoice_desc = " ".join(p for p in invoice_parts if p)[:40]

    # 3. SHORT_DESC
    with_str = f" {with_feature}" if with_feature else ""
    series_part = f" {series_str}" if series_str else ""
    cycles_part = f", {cycles}-Wash Cycle" if cycles else ""
    mount_part = f", {mounting_type} Mounting" if mounting_type else ""
    mat_part = f", {material}" if material else ""
    color_part = f", {color}" if color else ""
    short_desc = f"{brand_str}{series_part} {mpn_str} {title_str}{with_str}{mount_part}{cycles_part}{mat_part}{color_part}".strip()

    # 4. LONG_DESC1 (Canonical Facts Concatenation)
    long_parts = [f"{brand_str} {title_str}{with_str}"]
    if series_str:
        long_parts.append(series_str)
    if cycles:
        long_parts.append(f"{cycles} Wash Cycles" if not str(cycles).endswith("Cycles") else cycles)
    if voltage:
        long_parts.append(f"{voltage} V" if not str(voltage).endswith("V") else voltage)
    if amperage:
        long_parts.append(f"{amperage} A" if not str(amperage).endswith("A") else amperage)
    if mounting_type:
        long_parts.append(f"{mounting_type} Mounting")
    if size:
        long_parts.append(size)
    if depth_door_open:
        long_parts.append(f"{depth_door_open} in Depth With Door Open" if not "Depth" in str(depth_door_open) else depth_door_open)
    if min_height:
        long_parts.append(f"{min_height} Minimum Height" if not "Height" in str(min_height) else min_height)
    if max_height:
        long_parts.append(f"{max_height} Maximum Height" if not "Height" in str(max_height) else max_height)
    if sound_level:
        long_parts.append(f"{sound_level} dBA Sound Level" if not "Sound" in str(sound_level) else sound_level)
    if material:
        long_parts.append(material)
    if color:
        long_parts.append(color)
    if additional_info:
        long_parts.append(f"Additional Information: {additional_info}")
    
    long_desc1 = ", ".join(p for p in long_parts if p)

    # 5. RETAIL_DESC (No brand prefix)
    series_title = f"{series_str} {title_str}" if series_str else title_str
    retail_desc = f"{series_title}{mount_part}{cycles_part}{mat_part}{color_part}".strip()

    # 6. MARKETING_DESCRIPTION (Requires verified evidence)
    marketing_desc = str(marketing_evidence).strip() if marketing_evidence else ""

    return {
        "MOBILE_DESC": mobile_desc,
        "INVOICE_DESC": invoice_desc,
        "SHORT_DESC": short_desc,
        "LONG_DESC1": long_desc1,
        "RETAIL_DESC": retail_desc,
        "MARKETING_DESCRIPTION": marketing_desc,
    }
