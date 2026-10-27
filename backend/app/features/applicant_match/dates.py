"""Role date parsing and experience arithmetic. Pure code: the model only copies date text from the resume.

Accepted: "Mar 2021", "March 2021", "03/2021", "3/2021", "2021-03", "2021/03", "2021", and Present / Current /
Now / Till date / To date / Ongoing (resolved to `as_of`). Year-only dates use a midpoint convention (start
July 1, end June 30) and are marked approximate. Month ends are exclusive (the 1st of the next month), so
"Jan 2020 – Dec 2020" is exactly one year.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from app.features.applicant_match.rounding import half_up

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTHS["sept"] = 9
PRESENT = re.compile(r"^(present|current|currently|now|till date|to date|today|ongoing|date)$", re.I)
_MONTH_YEAR = re.compile(r"^([a-z]{3,9})\.?,?\s*'?(\d{4}|\d{2})$", re.I)
_NUM_MONTH_YEAR = re.compile(r"^(\d{1,2})\s*[/.\-]\s*(\d{4})$")
_YEAR_MONTH = re.compile(r"^(\d{4})\s*[/.\-]\s*(\d{1,2})$")
_YEAR = re.compile(r"^(\d{4})$")
DAYS_PER_YEAR = 365.25


@dataclass(frozen=True)
class ParsedDate:
    value: date
    approximate: bool = False
    present: bool = False


def _year(y: str) -> int | None:
    n = int(y)
    if len(y) == 2:
        n += 2000 if n <= 50 else 1900
    return n if 1950 <= n <= 2100 else None


def _next_month(y: int, m: int) -> date:
    return date(y + (m == 12), 1 if m == 12 else m + 1, 1)


def parse_date(text: str | None, *, end: bool, as_of: date) -> ParsedDate | None:
    if not text:
        return None
    t = " ".join(text.strip().strip(".,()").split())
    if PRESENT.match(t):
        return ParsedDate(as_of, present=True)
    month: int | None = None
    year: int | None = None
    if m := _MONTH_YEAR.match(t):
        month = MONTHS.get(m.group(1)[:4].casefold()) or MONTHS.get(m.group(1)[:3].casefold())
        year = _year(m.group(2))
    elif m := _NUM_MONTH_YEAR.match(t):
        month, year = int(m.group(1)), _year(m.group(2))
    elif m := _YEAR_MONTH.match(t):
        year, month = _year(m.group(1)), int(m.group(2))
    elif m := _YEAR.match(t):
        year = _year(m.group(1))
        if year is None:
            return None
        return ParsedDate(date(year, 6, 30) if end else date(year, 7, 1), approximate=True)
    if year is None or month is None or not 1 <= month <= 12:
        return None
    return ParsedDate(_next_month(year, month) if end else date(year, month, 1))


def merge_intervals(intervals: list[tuple[date, date]]) -> list[tuple[date, date]]:
    merged: list[tuple[date, date]] = []
    for s, e in sorted(i for i in intervals if i[1] > i[0]):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def years_of(intervals: list[tuple[date, date]]) -> float | None:
    """Union length in years, one decimal. Overlapping roles count once. None when there is nothing dated."""
    merged = merge_intervals(intervals)
    if not merged:
        return None
    days = sum((e - s).days for s, e in merged)
    return half_up(days / DAYS_PER_YEAR, 1)
