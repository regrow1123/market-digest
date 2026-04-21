"""Infer accent direction (up/down/neutral) for a rating item."""
from __future__ import annotations

import re
from typing import Literal

Direction = Literal["up", "down", "neutral"]

_ARROW_RE = re.compile(r"(.+?)(?:→|->)(.+)")
_NUMBER_RE = re.compile(r"[\d]+(?:,\d+)*(?:\.\d+)?")

_UP_OPINIONS = frozenset({
    "buy", "strong buy", "outperform", "overweight",
    "accumulate", "market outperform", "add", "positive",
})
_DOWN_OPINIONS = frozenset({
    "sell", "strong sell", "underperform", "underweight",
    "reduce", "negative",
})


def _last_number(text: str) -> float | None:
    matches = _NUMBER_RE.findall(text)
    if not matches:
        return None
    try:
        return float(matches[-1].replace(",", ""))
    except ValueError:
        return None


def infer_direction(opinion: str | None, target: str | None) -> Direction:
    """Return up/down/neutral for a card item.

    Priority:
      1. target with arrow ('→' or '->') — compare the last number on each side.
      2. opinion text dictionary lookup (case-insensitive).
      3. neutral as safe default.
    """
    if target:
        m = _ARROW_RE.match(target)
        if m:
            left = _last_number(m.group(1))
            right = _last_number(m.group(2))
            if left is not None and right is not None:
                if right > left:
                    return "up"
                if right < left:
                    return "down"
                return "neutral"
    if opinion:
        key = opinion.strip().lower()
        if key in _UP_OPINIONS:
            return "up"
        if key in _DOWN_OPINIONS:
            return "down"
    return "neutral"
