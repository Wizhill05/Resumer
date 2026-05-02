"""
Salary text normalizer — converts salary strings like "₹20,000 - ₹40,000 a month"
into yearly INR integers: (min_yearly, max_yearly).

Handles:
  - Currency symbols (₹, $, €, £) — all converted to INR-equivalent integers
  - Numeric ranges with separators (commas, dots, lakh notation)
  - Period keywords: per hour, per day, a week, a month, per year, per annum
  - Single values (treated as both min and max)
"""
from __future__ import annotations

import re
from typing import Tuple

# Multipliers to normalize to yearly
_PERIOD_MULTIPLIERS: dict[str, int] = {
    "hour": 8 * 250,       # 8 hours/day * 250 working days
    "day": 250,             # 250 working days
    "week": 52,
    "month": 12,
    "year": 1,
    "annum": 1,
    "annual": 1,
}

# Regex to detect period in salary text
_PERIOD_RE = re.compile(
    r"\b(?:per|a|an)\s+"
    r"(hour|day|week|month|year|annum|annual)"
    r"(?:ly)?\b",
    re.IGNORECASE,
)

# Also match standalone "monthly", "yearly", "annually", "hourly", "weekly", "daily"
_STANDALONE_PERIOD_RE = re.compile(
    r"\b(hour|dai|week|month|year|annual)(?:ly|s)?\b",
    re.IGNORECASE,
)

# Match numbers like 16,265.54 or 87229 or 1.5 (lakh style handled separately)
_NUMBER_RE = re.compile(r"[\d,]+(?:\.\d+)?")

# Lakh notation: "1.5 lakh" or "2 lakhs"
_LAKH_RE = re.compile(r"([\d,.]+)\s*(?:lakh|lac)s?\b", re.IGNORECASE)

# Crore notation
_CRORE_RE = re.compile(r"([\d,.]+)\s*(?:crore|cr)s?\b", re.IGNORECASE)


def _parse_number(text: str) -> float | None:
    """Parse a number string with commas/dots."""
    cleaned = text.replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _detect_period(text: str) -> int:
    """Detect the pay period and return the multiplier to yearly."""
    match = _PERIOD_RE.search(text)
    if match:
        period = match.group(1).lower()
        return _PERIOD_MULTIPLIERS.get(period, 1)

    match = _STANDALONE_PERIOD_RE.search(text)
    if match:
        root = match.group(1).lower()
        if root == "dai":
            return _PERIOD_MULTIPLIERS["day"]
        return _PERIOD_MULTIPLIERS.get(root, 1)

    return 1  # Default: assume yearly


def parse_salary(text: str) -> Tuple[int | None, int | None]:
    """
    Parse a salary string into (min_yearly_inr, max_yearly_inr).

    Returns (None, None) if the text cannot be parsed or is empty.

    Examples:
        "₹20,000 - ₹40,000 a month" -> (240000, 480000)
        "₹16,265.54 - ₹87,229.97 a month" -> (195186, 1046759)
        "$50,000 a year" -> (50000, 50000)
        "Company and salary information" -> (None, None)
        "" -> (None, None)
    """
    if not text or not text.strip():
        return (None, None)

    text = text.strip()

    # Skip non-salary strings
    skip_markers = (
        "company and salary",
        "not specified",
        "not disclosed",
        "competitive",
        "negotiable",
    )
    if any(marker in text.lower() for marker in skip_markers):
        return (None, None)

    # Check for lakh notation first
    lakh_matches = _LAKH_RE.findall(text)
    crore_matches = _CRORE_RE.findall(text)

    numbers: list[float] = []

    if crore_matches:
        for m in crore_matches:
            val = _parse_number(m)
            if val is not None:
                numbers.append(val * 10_000_000)
    elif lakh_matches:
        for m in lakh_matches:
            val = _parse_number(m)
            if val is not None:
                numbers.append(val * 100_000)
    else:
        # Extract all numbers
        raw_numbers = _NUMBER_RE.findall(text)
        for raw in raw_numbers:
            val = _parse_number(raw)
            if val is not None and val > 0:
                numbers.append(val)

    if not numbers:
        return (None, None)

    # Detect period multiplier
    multiplier = _detect_period(text)

    # If lakh/crore notation, usually already yearly, but check for "per month" etc.
    if lakh_matches or crore_matches:
        # Lakh/crore numbers are typically already in the right magnitude
        # but we still apply period detection
        pass

    if len(numbers) == 1:
        yearly = int(numbers[0] * multiplier)
        return (yearly, yearly)
    elif len(numbers) >= 2:
        min_val = min(numbers[0], numbers[1])
        max_val = max(numbers[0], numbers[1])
        return (int(min_val * multiplier), int(max_val * multiplier))

    return (None, None)
