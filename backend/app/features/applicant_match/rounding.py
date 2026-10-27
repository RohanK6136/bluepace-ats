"""Half-up rounding (Python's round() is half-even and float-sensitive; card numbers must not be)."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def half_up(value: float, digits: int = 0) -> float:
    q = Decimal(1).scaleb(-digits)
    return float(Decimal(repr(value)).quantize(q, rounding=ROUND_HALF_UP))


def pct(numerator: float, denominator: float) -> int | None:
    """Whole percent, rounded half up; None when there is nothing to score (category excluded)."""
    if denominator <= 0:
        return None
    return int(half_up(numerator / denominator * 100))
