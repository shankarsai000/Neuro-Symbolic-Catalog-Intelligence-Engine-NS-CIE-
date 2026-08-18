from __future__ import annotations

import re
from typing import Any

# Regex pattern targeting Unilog placeholder noise (case-insensitive)
PLACEHOLDER_PATTERN = re.compile(
    r"--\s*(?:Unbranded|No\s+Unilog\s+Brand|No\s+DIB\s+Brand|Unassigned|Not\s+Applicable|N/A)\s*--",
    re.IGNORECASE,
)

MULTIPLE_SPACES_PATTERN = re.compile(r"\s+")

NULL_EQUIVALENTS = {"nan", "none", "null", "<na>", "n/a", ""}


def clean_placeholders(text: Any) -> str | None:
    """Aggressively remove Unilog-specific placeholder noise from strings.

    Removes strings such as '-- Unbranded --', '-- No Unilog Brand --',
    '-- No DIB Brand --', collapses multiple whitespace characters,
    and returns a cleaned string or None if the result is empty or null-equivalent.

    Args:
        text: Input string or value to sanitize.

    Returns:
        Cleaned string or None if empty/null/NaN.
    """
    if text is None:
        return None

    # Handle non-string types safely (e.g. pandas NaN or float/int)
    if not isinstance(text, str):
        text = str(text)

    stripped = text.strip()
    if stripped.lower() in NULL_EQUIVALENTS:
        return None

    # Remove placeholder noise
    cleaned = PLACEHOLDER_PATTERN.sub(" ", stripped)

    # Collapse multiple whitespace and strip
    cleaned = MULTIPLE_SPACES_PATTERN.sub(" ", cleaned).strip()

    if not cleaned or cleaned.lower() in NULL_EQUIVALENTS:
        return None

    return cleaned
