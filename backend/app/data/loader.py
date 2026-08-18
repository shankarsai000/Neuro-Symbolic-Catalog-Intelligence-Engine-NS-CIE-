from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# Standard fallback dictionary for fractional conversions
FALLBACK_DECIMAL_FRACTIONS: dict[float, str] = {
    0.03125: "1/32",
    0.046875: "3/64",
    0.0625: "1/16",
    0.09375: "3/32",
    0.125: "1/8",
    0.15625: "5/32",
    0.1875: "3/16",
    0.21875: "7/32",
    0.25: "1/4",
    0.28125: "9/32",
    0.3125: "5/16",
    0.34375: "11/32",
    0.375: "3/8",
    0.40625: "13/32",
    0.4375: "7/16",
    0.46875: "15/32",
    0.5: "1/2",
    0.53125: "17/32",
    0.5625: "9/16",
    0.59375: "19/32",
    0.625: "5/8",
    0.65625: "21/32",
    0.6875: "11/16",
    0.71875: "23/32",
    0.75: "3/4",
    0.78125: "25/32",
    0.8125: "13/16",
    0.84375: "27/32",
    0.875: "7/8",
    0.90625: "29/32",
    0.9375: "15/16",
    0.96875: "31/32",
}

# Standard fallback dictionary for UOM canonicalization
FALLBACK_UOM_STANDARDS: dict[str, str] = {
    "in": "in",
    "inch": "in",
    "inches": "in",
    "\"": "in",
    "ft": "ft",
    "foot": "ft",
    "feet": "ft",
    "'": "ft",
    "yd": "yd",
    "yard": "yd",
    "yards": "yd",
    "mm": "mm",
    "cm": "cm",
    "m": "m",
    "v": "V",
    "volt": "V",
    "volts": "V",
    "kv": "kV",
    "a": "A",
    "amp": "A",
    "amps": "A",
    "ampere": "A",
    "amperes": "A",
    "ma": "mA",
    "w": "W",
    "watt": "W",
    "watts": "W",
    "kw": "kW",
    "hp": "HP",
    "hz": "Hz",
    "khz": "kHz",
    "mhz": "MHz",
    "ghz": "GHz",
    "rpm": "RPM",
    "dba": "dBA",
    "db": "dB",
    "psi": "psi",
    "oz": "oz",
    "lb": "lb",
    "lbs": "lb",
    "kg": "kg",
    "g": "g",
    "deg": "deg",
    "gal": "gal",
    "gpm": "GPM",
    "cfm": "CFM",
}


class MasterDataLoader:
    """Master Data Loader for Unilog standard lookup files.

    Loads lookup tables into memory as high-performance dictionaries,
    with built-in fallback fixtures for resilient offline execution.
    """

    def __init__(self, data_dir: Path | str | None = None) -> None:
        if data_dir is None:
            self.data_dir = Path(__file__).resolve().parent
        else:
            self.data_dir = Path(data_dir)

        self._fraction_map: dict[float, str] | None = None
        self._uom_map: dict[str, str] | None = None

    def load_decimal_fractions(
        self, filepath: Path | str | None = None
    ) -> dict[float, str]:
        """Load Decimal_Fraction.xlsx or return the fallback mapping."""
        if self._fraction_map is not None and filepath is None:
            return self._fraction_map

        target_file = (
            Path(filepath)
            if filepath
            else self.data_dir / "Decimal_Fraction.xlsx"
        )

        mapping: dict[float, str] = dict(FALLBACK_DECIMAL_FRACTIONS)

        if target_file.exists():
            try:
                df = pd.read_excel(target_file)
                # Attempt to parse common column name variations
                decimal_col = next(
                    (col for col in df.columns if "dec" in str(col).lower()),
                    df.columns[0] if len(df.columns) > 0 else None,
                )
                fraction_col = next(
                    (col for col in df.columns if "frac" in str(col).lower()),
                    df.columns[1] if len(df.columns) > 1 else None,
                )

                if decimal_col is not None and fraction_col is not None:
                    for _, row in df.iterrows():
                        try:
                            dec_val = float(row[decimal_col])
                            frac_val = str(row[fraction_col]).strip()
                            if frac_val and frac_val != "nan":
                                mapping[round(dec_val, 5)] = frac_val
                        except (ValueError, TypeError):
                            continue
                logger.info(f"Loaded {len(mapping)} decimal fraction rules from {target_file}")
            except Exception as e:
                logger.warning(
                    f"Could not load {target_file} ({e}); using fallback decimal fractions"
                )
        else:
            logger.debug(
                f"File {target_file} not found; using fallback decimal fractions ({len(mapping)} entries)"
            )

        self._fraction_map = mapping
        return self._fraction_map

    def load_uom_standards(
        self, filepath: Path | str | None = None
    ) -> dict[str, str]:
        """Load Unilog_Master_UOM_Standards.xlsx or return the fallback mapping."""
        if self._uom_map is not None and filepath is None:
            return self._uom_map

        target_file = (
            Path(filepath)
            if filepath
            else self.data_dir / "Unilog_Master_UOM_Standards.xlsx"
        )

        mapping: dict[str, str] = dict(FALLBACK_UOM_STANDARDS)

        if target_file.exists():
            try:
                df = pd.read_excel(target_file)
                raw_col = next(
                    (col for col in df.columns if "raw" in str(col).lower() or "input" in str(col).lower()),
                    df.columns[0] if len(df.columns) > 0 else None,
                )
                std_col = next(
                    (col for col in df.columns if "standard" in str(col).lower() or "uom" in str(col).lower()),
                    df.columns[1] if len(df.columns) > 1 else None,
                )

                if raw_col is not None and std_col is not None:
                    for _, row in df.iterrows():
                        raw_val = str(row[raw_col]).strip().lower()
                        std_val = str(row[std_col]).strip()
                        if raw_val and raw_val != "nan" and std_val and std_val != "nan":
                            mapping[raw_val] = std_val
                logger.info(f"Loaded {len(mapping)} UOM standard rules from {target_file}")
            except Exception as e:
                logger.warning(
                    f"Could not load {target_file} ({e}); using fallback UOM standards"
                )
        else:
            logger.debug(
                f"File {target_file} not found; using fallback UOM standards ({len(mapping)} entries)"
            )

        self._uom_map = mapping
        return self._uom_map


# Default global loader instance
master_data_loader = MasterDataLoader()
