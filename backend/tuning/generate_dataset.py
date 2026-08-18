from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an industrial catalog specialist for the NS-CIE extraction engine. "
    "Extract structured technical parameters from the product description into JSON. "
    "Return ONLY a valid JSON object matching the exact schema without explanations, markdown headers, or chatter:\n"
    "{\n"
    '  "brand": string or null,\n'
    '  "item_type": string or null,\n'
    '  "mpn": string or null,\n'
    '  "voltage": string or null,\n'
    '  "dimensions": string or null,\n'
    '  "mounting": string or null,\n'
    '  "material": string or null,\n'
    '  "invoice_desc": string,\n'
    '  "raw_specs": {}\n'
    "}"
)

# Mock training samples representing Unilog catalog ground-truth records
MOCK_GROUND_TRUTH_SAMPLES = [
    {
        "Raw_Input": "PDSH4816AF Dishwasher SS 120v 50.25in -- Unbranded -- | Manufacturer: FRIGIDAIRE",
        "Expected_Invoice_Desc": "DISHWASHER LEG 5 SST 120V 15A 50-1/4IN",
        "Expected_Extracted_JSON": {
            "brand": "FRIGIDAIRE®",
            "item_type": "Dishwasher",
            "mpn": "PDSH4816AF",
            "voltage": "120 V",
            "dimensions": "50-1/4 in",
            "mounting": "Leg",
            "material": "Stainless Steel",
            "invoice_desc": "DISHWASHER LEG 5 SST 120V 15A 50-1/4IN",
            "raw_specs": {"amperage": "15 A", "wash_cycles": "5"},
        },
    },
    {
        "Raw_Input": "WDTS7024RZ Dishwasher SS 120v 10a 41dba -- No Unilog Brand -- | Manufacturer: Whirlpool Corporation",
        "Expected_Invoice_Desc": "DISHWASHER BLTLN SST SST 120V 10A 41DBA",
        "Expected_Extracted_JSON": {
            "brand": "WHIRLPOOL®",
            "item_type": "Dishwasher",
            "mpn": "WDTS7024RZ",
            "voltage": "120 V",
            "dimensions": "50-3/16 in",
            "mounting": "Built-in",
            "material": "Stainless Steel",
            "invoice_desc": "DISHWASHER BLTLN SST SST 120V 10A 41DBA",
            "raw_specs": {"amperage": "10 A", "sound_level": "41 dBA"},
        },
    },
    {
        "Raw_Input": "49-94-0013 Milw 5\"x.045\"x7/8\" Metal Cut Off Disc -- No DIB Brand -- | Manufacturer: Milwaukee Accessory (4031)",
        "Expected_Invoice_Desc": "5\" X .045\" X 7/8\" CUT OFF DISC",
        "Expected_Extracted_JSON": {
            "brand": "MILWAUKEE®",
            "item_type": "Cut-Off Disc",
            "mpn": "49-94-0013",
            "voltage": None,
            "dimensions": "5 in x 3/64 in x 7/8 in",
            "mounting": None,
            "material": "Metal / Abrasive",
            "invoice_desc": "5\" X .045\" X 7/8\" CUT OFF DISC",
            "raw_specs": {"application": "Metal Cutting"},
        },
    },
    {
        "Raw_Input": "DCB518ASTS06G Diablo 1/2\"x18\" Sanding Belt 6pc -- Unbranded -- | Manufacturer: Freud Inc (2435)",
        "Expected_Invoice_Desc": "1/2\" X 18\" SANDING BELT 6PK",
        "Expected_Extracted_JSON": {
            "brand": "FREUD®",
            "item_type": "Sanding Belt",
            "mpn": "DCB518ASTS06G",
            "voltage": None,
            "dimensions": "1/2 in x 18 in",
            "mounting": None,
            "material": "Cloth / Abrasive",
            "invoice_desc": "1/2\" X 18\" SANDING BELT 6PK",
            "raw_specs": {"pack_quantity": "6pc"},
        },
    },
    {
        "Raw_Input": "5B-332-080 HIOLIT 5\" P80 Abrasive Disc -- Unbranded -- | Manufacturer: Mirka Abrasives Inc (MIRUS)",
        "Expected_Invoice_Desc": "5\" P80 HIOLIT ABRASIVE DISC",
        "Expected_Extracted_JSON": {
            "brand": "MIRKA®",
            "item_type": "Abrasive Disc",
            "mpn": "5B-332-080",
            "voltage": None,
            "dimensions": "5 in",
            "mounting": None,
            "material": "Abrasive / Aluminum Oxide",
            "invoice_desc": "5\" P80 HIOLIT ABRASIVE DISC",
            "raw_specs": {"grit": "P80"},
        },
    },
]


def load_dataset_dataframe(input_path: Optional[Path | str] = None) -> pd.DataFrame:
    """Load real input/output dataset if available, or generate mock training DataFrame."""
    if input_path and Path(input_path).exists():
        try:
            target = Path(input_path)
            if target.suffix.lower() in (".xlsx", ".xls"):
                df = pd.read_excel(target)
            else:
                df = pd.read_csv(target)
            logger.info(f"Loaded {len(df)} rows from {input_path}")
            return df
        except Exception as e:
            logger.warning(f"Failed loading {input_path} ({e}); falling back to mock dataset")

    # Fallback to mock dataset DataFrame
    df = pd.DataFrame(MOCK_GROUND_TRUTH_SAMPLES)
    return df


def generate_chatml_jsonl(
    df: pd.DataFrame,
    output_path: Path | str,
) -> int:
    """Transform dataset DataFrame into OpenAI ChatML formatted JSONL file.

    Args:
        df: Input DataFrame with Raw_Input, Expected_Invoice_Desc, Expected_Extracted_JSON.
        output_path: Destination JSONL filepath.

    Returns:
        Number of generated training records.
    """
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    records_count = 0
    with open(out_file, "w", encoding="utf-8") as f:
        for _, row in df.iterrows():
            raw_input = str(row.get("Raw_Input", "")).strip()
            if not raw_input:
                continue

            extracted_data = row.get("Expected_Extracted_JSON", {})
            if isinstance(extracted_data, str):
                try:
                    extracted_data = json.loads(extracted_data)
                except Exception:
                    extracted_data = {"raw_text": extracted_data}

            assistant_content = json.dumps(extracted_data, ensure_ascii=False)

            chatml_entry = {
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": raw_input},
                    {"role": "assistant", "content": assistant_content},
                ]
            }

            f.write(json.dumps(chatml_entry, ensure_ascii=False) + "\n")
            records_count += 1

    logger.info(f"Successfully generated {records_count} ChatML records in {out_file}")
    return records_count


def main() -> None:
    """CLI entry point for fine-tuning dataset generation."""
    tuning_dir = Path(__file__).resolve().parent
    output_jsonl = tuning_dir / "train.jsonl"

    df = load_dataset_dataframe()
    count = generate_chatml_jsonl(df, output_jsonl)
    print(f"[SUCCESS] Generated {count} fine-tuning records -> {output_jsonl}")


if __name__ == "__main__":
    main()
