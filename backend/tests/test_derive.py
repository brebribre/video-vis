"""Period parsing and unit conversion — the two places a guess corrupts data."""

from __future__ import annotations

import pytest

from app.canvas import derive


@pytest.mark.parametrize(
    ("label", "iso", "granularity"),
    [
        ("2024", "2024", "year"),
        ("FY2024", "2024", "year"),
        ("FY 2024", "2024", "year"),
        ("fiscal year 2024", "2024", "year"),
        ("CY2025", "2025", "year"),
        ("2024-06", "2024-06", "month"),
        ("2024/6", "2024-06", "month"),
        ("06/2024", "2024-06", "month"),
        ("Jun 2024", "2024-06", "month"),
        ("June 2024", "2024-06", "month"),
        ("Q1 2025", "2025-01", "quarter"),
        ("Q3 2025", "2025-07", "quarter"),
        ("2025 Q4", "2025-10", "quarter"),
        ("H1 2024", "2024-01", "quarter"),
        ("2024 H2", "2024-07", "quarter"),
    ],
)
def test_parses_the_forms_sources_actually_use(label, iso, granularity):
    period = derive.parse_period(label)
    assert period is not None, label
    assert period.iso == iso
    assert period.granularity == granularity


@pytest.mark.parametrize(
    "label",
    ["", "sometime in 2024", "last year", "Q5 2024", "2024-13", "13/2024", "24"],
)
def test_refuses_to_guess_an_unreadable_period(label):
    # Returning None is the feature: the row gets flagged and the agent is asked
    # to restate it, rather than a wrong `time` silently mis-plotting a point.
    assert derive.parse_period(label) is None


def test_quarters_order_correctly_against_each_other():
    quarters = [derive.parse_period(f"Q{q} 2025") for q in (1, 2, 3, 4)]
    keys = [p.sort_key for p in quarters]  # type: ignore[union-attr]
    assert keys == sorted(keys)


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        (1.5, "USD_billions", 1.5e9),
        (250.0, "USD_millions", 2.5e8),
        (4.0, "USD_thousands", 4000.0),
        (42.0, "USD", 42.0),
        (99.0, "count", 99.0),
    ],
)
def test_converts_units_to_a_common_base(value, unit, expected):
    result = derive.normalize_value(value, unit)
    assert result is not None
    assert result[0] == pytest.approx(expected)


def test_mixed_units_become_comparable():
    # 1.5 billion and 1500 million are the same number expressed two ways; the
    # whole point of normalising is that a chart can plot them together.
    billions = derive.normalize_value(1.5, "USD_billions")
    millions = derive.normalize_value(1500.0, "USD_millions")
    assert billions[0] == pytest.approx(millions[0])  # type: ignore[index]


def test_unknown_unit_is_rejected_not_assumed():
    assert derive.normalize_value(1.0, "EUR_millions") is None


def test_axis_mode_follows_the_finest_granularity_present():
    years = [derive.parse_period("2024"), derive.parse_period("2025")]
    assert derive.axis_mode_for(years) == "year"  # type: ignore[arg-type]

    mixed = [derive.parse_period("2024"), derive.parse_period("Q3 2025")]
    # A quarterly series next to an annual one must resolve to the finer axis,
    # or the quarters collapse onto the year ticks.
    assert derive.axis_mode_for(mixed) == "date-mmyy"  # type: ignore[arg-type]


def test_time_matches_the_frontend_parsers():
    year = derive.parse_period("2024")
    assert derive.time_for(year, "year") == 2024.0  # type: ignore[arg-type]

    month = derive.parse_period("2024-06")
    # DataInput.vue builds date modes from Date.UTC(...) epoch milliseconds.
    assert derive.time_for(month, "date-mmyy") == 1717200000000.0  # type: ignore[arg-type]


def test_expand_periods_finds_the_holes():
    start, end = derive.parse_period("2020"), derive.parse_period("2024")
    expanded = derive.expand_periods(start, end, "year")  # type: ignore[arg-type]
    assert [p.iso for p in expanded] == ["2020", "2021", "2022", "2023", "2024"]


def test_expand_periods_crosses_a_year_boundary():
    start, end = derive.parse_period("2024-11"), derive.parse_period("2025-02")
    expanded = derive.expand_periods(start, end, "month")  # type: ignore[arg-type]
    assert [p.iso for p in expanded] == ["2024-11", "2024-12", "2025-01", "2025-02"]
