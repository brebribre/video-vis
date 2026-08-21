"""Canvas behaviour: the URL guard, conflicts, gaps, persistence, finalisation."""

from __future__ import annotations

import pytest

from app.canvas.store import (
    STATUS_CONFLICT,
    STATUS_OK,
    CanvasStore,
    canonical_url,
)

SEARCHED = "https://example.com/openai-revenue-2024"
ALSO_SEARCHED = "https://news.example.org/ai-revenue-2025"


def store_with_urls(*urls: str) -> CanvasStore:
    store = CanvasStore("run-test")
    store.allow_urls(urls or (SEARCHED, ALSO_SEARCHED))
    return store


def row(**overrides):
    base = {
        "series": "OpenAI",
        "period_label": "2024",
        "raw_value": 3700.0,
        "raw_unit": "USD_millions",
        "source_url": SEARCHED,
        "source_title": "OpenAI revenue",
        "cited_text": "OpenAI reached $3.7bn in 2024",
        "published_at": "2025-01-15",
    }
    return {**base, **overrides}


# --- §4.2 the anti-fabrication guard ------------------------------------


def test_rejects_a_url_that_was_never_retrieved():
    store = store_with_urls(SEARCHED)
    [result] = store.append_rows([row(source_url="https://fabricated.example/invented")])

    assert not result.accepted
    assert "not returned by any search" in result.reason
    # And nothing is recorded — a rejected row must not reach the chart.
    assert store.rows == []


def test_the_rejection_tells_the_agent_how_to_fix_it():
    store = store_with_urls(SEARCHED)
    [result] = store.append_rows([row(source_url="https://fabricated.example/x")])
    assert "do not construct one" in result.reason


def test_accepts_a_url_that_search_actually_returned():
    store = store_with_urls(SEARCHED)
    [result] = store.append_rows([row()])
    assert result.accepted
    assert store.rows[0].status == STATUS_OK


def test_url_matching_ignores_cosmetic_differences():
    store = store_with_urls("https://www.example.com/a/b/")
    [result] = store.append_rows([row(source_url="https://example.com/a/b#section")])
    assert result.accepted, "trailing slash, www and fragment must not defeat the guard"


def test_url_matching_keeps_the_query_string():
    # The query often selects the very document being cited, so dropping it
    # would let a row cite a different page than the one retrieved.
    assert canonical_url("https://e.com/doc?id=1") != canonical_url("https://e.com/doc?id=2")


def test_a_source_url_is_required():
    store = store_with_urls()
    [result] = store.append_rows([{k: v for k, v in row().items() if k != "source_url"}])
    assert not result.accepted
    assert "source_url" in result.reason


# --- input validation -----------------------------------------------------


def test_rejects_an_unparseable_period_with_guidance():
    store = store_with_urls()
    [result] = store.append_rows([row(period_label="sometime last year")])
    assert not result.accepted
    assert "could not be parsed" in result.reason
    assert "FY2024" in result.reason  # shows the accepted forms


def test_rejects_an_unknown_unit():
    store = store_with_urls()
    [result] = store.append_rows([row(raw_unit="EUR_millions")])
    assert not result.accepted
    assert "unknown raw_unit" in result.reason


def test_rejects_a_non_numeric_value():
    store = store_with_urls()
    [result] = store.append_rows([row(raw_value="about three billion")])
    assert not result.accepted
    assert "not a number" in result.reason


# --- §4.4 derived columns -------------------------------------------------


def test_mixed_units_normalise_to_a_common_scale():
    store = store_with_urls()
    store.append_rows(
        [
            row(series="OpenAI", period_label="2024", raw_value=3700, raw_unit="USD_millions"),
            row(series="Anthropic", period_label="2024", raw_value=0.85, raw_unit="USD_billions"),
        ]
    )
    values = {r.series: r.value_normalized for r in store.rows}
    assert values["OpenAI"] == pytest.approx(3.7e9)
    assert values["Anthropic"] == pytest.approx(0.85e9)


# --- §9.2 conflicting sources --------------------------------------------


def test_newest_publication_wins_and_the_loser_is_kept_visible():
    store = store_with_urls()
    store.append_rows(
        [
            row(raw_value=3400, source_url=SEARCHED, published_at="2024-11-01"),
            row(raw_value=3700, source_url=ALSO_SEARCHED, published_at="2025-06-01"),
        ]
    )
    by_value = {r.raw_value: r.status for r in store.rows}
    assert by_value[3700.0] == STATUS_OK, "the later publication should win"
    assert by_value[3400.0] == STATUS_CONFLICT, "the superseded row stays visible, not deleted"


def test_a_conflict_is_surfaced_with_both_sides():
    store = store_with_urls()
    store.append_rows(
        [
            row(raw_value=3400, source_url=SEARCHED, published_at="2024-11-01"),
            row(raw_value=3700, source_url=ALSO_SEARCHED, published_at="2025-06-01"),
        ]
    )
    [conflict] = store.gap_report()["conflicts"]
    assert conflict["series"] == "OpenAI"
    assert conflict["kept"]["value"] == pytest.approx(3.7e9)
    assert conflict["superseded"]["value"] == pytest.approx(3.4e9)


def test_rounding_differences_are_not_treated_as_a_conflict():
    store = store_with_urls()
    store.append_rows(
        [
            row(raw_value=3700, source_url=SEARCHED),
            row(raw_value=3701, source_url=ALSO_SEARCHED),
        ]
    )
    assert all(r.status == STATUS_OK for r in store.rows)


def test_only_the_winner_reaches_the_chart():
    store = store_with_urls()
    store.append_rows(
        [
            row(raw_value=3400, source_url=SEARCHED, published_at="2024-11-01"),
            row(raw_value=3700, source_url=ALSO_SEARCHED, published_at="2025-06-01"),
        ]
    )
    series, _, _ = store.finalize()
    assert [p.value for p in series[0].data] == [pytest.approx(3.7e9)]


# --- §4.3 / §9.1 the gap report -------------------------------------------


def test_a_late_starting_series_is_not_reported_as_missing_early_years():
    # §9.1: OpenAI 2020-2021, Anthropic 2021 only. Anthropic starts late by
    # design and must not be asked to fill 2020.
    store = store_with_urls()
    store.append_rows(
        [
            row(series="OpenAI", period_label="2020", raw_value=100),
            row(series="OpenAI", period_label="2021", raw_value=200),
            row(series="Anthropic", period_label="2021", raw_value=10),
        ]
    )
    assert store.gap_report()["missing"] == []


def test_a_hole_inside_a_series_coverage_is_reported():
    store = store_with_urls()
    store.append_rows(
        [
            row(series="OpenAI", period_label="2020", raw_value=100),
            row(series="OpenAI", period_label="2022", raw_value=500),
        ]
    )
    [gap] = store.gap_report()["missing"]
    assert gap["series"] == "OpenAI"
    assert gap["missing_periods"] == ["2021"]


def test_the_range_is_the_union_of_all_series():
    store = store_with_urls()
    store.append_rows(
        [
            row(series="OpenAI", period_label="2020", raw_value=100),
            row(series="Anthropic", period_label="2023", raw_value=200),
        ]
    )
    assert store.gap_report()["range"] == {
        "start": "2020",
        "end": "2023",
        "granularity": "year",
    }


def test_an_empty_canvas_reports_cleanly():
    report = store_with_urls().gap_report()
    assert report["range"] is None
    assert report["missing"] == []


# --- revise / drop ---------------------------------------------------------


def test_revising_a_row_recomputes_its_derived_columns():
    store = store_with_urls()
    [added] = store.append_rows([row(raw_value=3700, raw_unit="USD_millions")])
    store.revise_row(added.row_id, raw_value=4.2, raw_unit="USD_billions")
    assert store.rows[0].value_normalized == pytest.approx(4.2e9)


def test_a_revision_cannot_smuggle_in_an_unverified_url():
    store = store_with_urls()
    [added] = store.append_rows([row()])
    result = store.revise_row(added.row_id, source_url="https://fabricated.example/x")
    assert not result.accepted
    assert store.rows[0].source_url == SEARCHED


def test_dropping_requires_a_reason():
    store = store_with_urls()
    [added] = store.append_rows([row()])
    assert not store.drop_row(added.row_id, reason="").accepted
    assert len(store.rows) == 1
    assert store.drop_row(added.row_id, reason="superseded by the 10-K").accepted
    assert store.rows == []


# --- persistence -----------------------------------------------------------


def test_round_trips_through_csv(tmp_path):
    store = CanvasStore("run-1", tmp_path)
    store.allow_urls([SEARCHED])
    store.append_rows([row()])
    path = store.persist()
    assert path.exists()

    reopened = CanvasStore.load("run-1", tmp_path, allowed_urls=[SEARCHED])
    assert len(reopened.rows) == 1
    assert reopened.rows[0].value_normalized == pytest.approx(3.7e9)
    assert reopened.rows[0].status == STATUS_OK


def test_reloading_without_the_url_set_invalidates_rows(tmp_path):
    # The allowed-URL set is per-run and deliberately not persisted: trusting
    # URLs recorded by an earlier run would weaken the §4.2 guard.
    store = CanvasStore("run-2", tmp_path)
    store.allow_urls([SEARCHED])
    store.append_rows([row()])
    store.persist()

    reopened = CanvasStore.load("run-2", tmp_path)
    assert reopened.rows[0].status == "unverified_url"


def test_reopened_rows_get_fresh_ids(tmp_path):
    store = CanvasStore("run-3", tmp_path)
    store.allow_urls([SEARCHED])
    store.append_rows([row()])
    store.persist()

    reopened = CanvasStore.load("run-3", tmp_path, allowed_urls=[SEARCHED])
    [added] = reopened.append_rows([row(period_label="2025", raw_value=12500)])
    assert added.accepted
    assert len({r.row_id for r in reopened.rows}) == 2, "row ids must not collide"


# --- §4.4 finalisation -----------------------------------------------------


def test_finalize_emits_renderer_shaped_series():
    store = store_with_urls()
    store.append_rows(
        [
            row(series="OpenAI", period_label="2024", raw_value=3700),
            row(series="OpenAI", period_label="2025", raw_value=12500),
            row(series="Anthropic", period_label="2025", raw_value=2400),
        ]
    )
    series, axis_mode, dimension = store.finalize()

    assert axis_mode == "year"
    assert dimension == "currency"
    assert [s.name for s in series] == ["OpenAI", "Anthropic"], "leader first"
    assert series[0].color == "#4f8ff7"
    assert [p.time for p in series[0].data] == [2024.0, 2025.0]
    assert [p.label for p in series[0].data] == ["2024", "2025"]


def test_finalize_never_backfills_a_missing_period():
    # §9.1: absence is the honest representation; a zero would assert the value
    # *was* zero, which no source said.
    store = store_with_urls()
    store.append_rows(
        [
            row(series="OpenAI", period_label="2020", raw_value=100),
            row(series="OpenAI", period_label="2021", raw_value=200),
            row(series="Anthropic", period_label="2021", raw_value=10),
        ]
    )
    series, _, _ = store.finalize()
    anthropic = next(s for s in series if s.name == "Anthropic")
    assert len(anthropic.data) == 1
    assert anthropic.data[0].time == 2021.0


def test_finalize_serialises_to_the_camelcase_the_renderer_expects():
    store = store_with_urls()
    store.append_rows([row()])
    series, _, _ = store.finalize()
    dumped = series[0].model_dump(by_alias=True)
    assert set(dumped) == {"name", "color", "data", "image"}
    assert set(dumped["data"][0]) == {"time", "label", "value"}
