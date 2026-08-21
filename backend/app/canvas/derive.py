"""Derived columns for the canvas — the Python half of §4.0.

The agent writes only what a source literally says; everything computed lives
here. Two rules shape this module:

1. **Never guess.** An unparseable period is flagged, not approximated. A wrong
   `time` silently mis-plots a point that a citation says is correct.
2. **Never invent data.** No zero-filling, no interpolation before a series'
   first real datapoint (§9.1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

Granularity = Literal["year", "quarter", "month"]

# raw_unit -> (multiplier to the dimension's base, dimension)
UNITS: dict[str, tuple[float, str]] = {
    "USD": (1.0, "currency"),
    "USD_thousands": (1e3, "currency"),
    "USD_millions": (1e6, "currency"),
    "USD_billions": (1e9, "currency"),
    "count": (1.0, "count"),
    "percent": (1.0, "percent"),
}

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# A quarter/half is anchored to the month it starts in, so ordering is correct
# and the renderer's date-mmyy axis can place it.
QUARTER_START = {1: 1, 2: 4, 3: 7, 4: 10}
HALF_START = {1: 1, 2: 7}


@dataclass(frozen=True)
class Period:
    year: int
    month: int | None  # None for a whole-year period
    granularity: Granularity

    @property
    def iso(self) -> str:
        if self.granularity == "year":
            return str(self.year)
        return f"{self.year:04d}-{self.month:02d}"

    @property
    def sort_key(self) -> tuple[int, int]:
        return (self.year, self.month or 0)


_YEAR = r"(?:19|20)\d{2}"

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # 2024-06, 2024/06
    (re.compile(rf"^({_YEAR})[-/](\d{{1,2}})$"), "year_month"),
    # 06/2024
    (re.compile(rf"^(\d{{1,2}})/({_YEAR})$"), "month_year"),
    # Q3 2025, Q3-2025, 2025 Q3
    (re.compile(rf"^q([1-4])\s*[-/ ]?\s*({_YEAR})$"), "quarter_year"),
    (re.compile(rf"^({_YEAR})\s*[-/ ]?\s*q([1-4])$"), "year_quarter"),
    # H1 2024, 2024 H2
    (re.compile(rf"^h([12])\s*[-/ ]?\s*({_YEAR})$"), "half_year"),
    (re.compile(rf"^({_YEAR})\s*[-/ ]?\s*h([12])$"), "year_half"),
    # Jun 2024, June 2024
    (re.compile(rf"^([a-z]{{3,9}})\.?\s+({_YEAR})$"), "monthname_year"),
    # 2024, FY2024, FY 2024, fiscal year 2024, CY2024
    (re.compile(rf"^(?:fy|cy|fiscal(?:\s+year)?|calendar(?:\s+year)?)?\s*({_YEAR})$"), "year"),
]


def parse_period(label: str) -> Period | None:
    """Canonicalise a verbatim period label, or None if it can't be read.

    Returning None is a feature: the caller flags the row `unparseable_period`
    and the agent gets told to restate it, rather than a bad guess reaching the
    chart.
    """
    if not label:
        return None
    text = label.strip().lower().replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", " ", text)

    for pattern, kind in _PATTERNS:
        match = pattern.match(text)
        if not match:
            continue

        if kind == "year":
            return Period(int(match.group(1)), None, "year")
        if kind == "year_month":
            year, month = int(match.group(1)), int(match.group(2))
            return Period(year, month, "month") if 1 <= month <= 12 else None
        if kind == "month_year":
            month, year = int(match.group(1)), int(match.group(2))
            return Period(year, month, "month") if 1 <= month <= 12 else None
        if kind in {"quarter_year", "year_quarter"}:
            quarter = int(match.group(1 if kind == "quarter_year" else 2))
            year = int(match.group(2 if kind == "quarter_year" else 1))
            return Period(year, QUARTER_START[quarter], "quarter")
        if kind in {"half_year", "year_half"}:
            half = int(match.group(1 if kind == "half_year" else 2))
            year = int(match.group(2 if kind == "half_year" else 1))
            return Period(year, HALF_START[half], "quarter")
        if kind == "monthname_year":
            month = MONTHS.get(match.group(1)[:3])
            return Period(int(match.group(2)), month, "month") if month else None
    return None


def normalize_value(raw_value: float, raw_unit: str) -> tuple[float, str] | None:
    """Convert to the base unit of its dimension. None if the unit is unknown.

    Returns `(value, dimension)`. Python does this rather than the model so the
    numbers stay checkable against the cited source (§4.0).
    """
    entry = UNITS.get(raw_unit)
    if entry is None:
        return None
    multiplier, dimension = entry
    return raw_value * multiplier, dimension


def parse_published_at(value: str | None) -> date | None:
    """Best-effort publication date, used only to break conflicts (§9.2)."""
    if not value:
        return None
    text = value.strip()
    for parser in (
        lambda t: datetime.fromisoformat(t.replace("Z", "+00:00")).date(),
        lambda t: datetime.strptime(t, "%Y-%m-%d").date(),
        lambda t: datetime.strptime(t, "%Y-%m").date(),
        lambda t: date(int(t), 1, 1),
    ):
        try:
            return parser(text)
        except (ValueError, TypeError):
            continue
    return None


def axis_mode_for(periods: list[Period]) -> str:
    """`year` only when every period is a whole year, else a month axis.

    Mixing a quarterly series with an annual one has to resolve to the finer
    axis or the quarters collapse onto each other.
    """
    if periods and all(p.granularity == "year" for p in periods):
        return "year"
    return "date-mmyy"


def time_for(period: Period, axis_mode: str) -> float:
    """The renderer's numeric `time` for a period, matching DataInput.vue.

    `year` mode uses the bare year; the date modes use epoch milliseconds, which
    is what the frontend's own parsers produce.
    """
    if axis_mode == "year":
        return float(period.year)
    epoch = datetime(period.year, period.month or 1, 1)
    return (epoch - datetime(1970, 1, 1)).total_seconds() * 1000.0


def label_for(period: Period, axis_mode: str) -> str:
    if axis_mode == "year":
        return str(period.year)
    return f"{period.month:02d}/{period.year % 100:02d}"


def expand_periods(start: Period, end: Period, granularity: Granularity) -> list[Period]:
    """Every period between two bounds, used to find holes in coverage (§4.3)."""
    if granularity == "year":
        return [Period(y, None, "year") for y in range(start.year, end.year + 1)]

    step = 3 if granularity == "quarter" else 1
    out: list[Period] = []
    year, month = start.year, start.month or 1
    while (year, month) <= (end.year, end.month or 1):
        out.append(Period(year, month, granularity))
        month += step
        while month > 12:
            month -= 12
            year += 1
    return out
