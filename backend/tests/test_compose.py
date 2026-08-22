"""Stage 3: caption sanitisation and ChartConfig assembly (§4.5)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.canvas.store import CanvasStore
from app.pipeline import compose as compose_module
from app.pipeline.captions import MIN_DURATION, sanitize_captions
from app.pipeline.compose import ComposeFailed, run_compose, suffixes_for

SEARCHED = "https://example.com/x"


# --- caption sanitisation --------------------------------------------------


def cap(text: str, appear_at: float, duration: float) -> dict[str, Any]:
    return {"text": text, "appearAt": appear_at, "duration": duration}


def test_well_spaced_captions_pass_through():
    kept, notes = sanitize_captions(
        [cap("a", 0, 2), cap("b", 3, 2)], animation_duration=8
    )
    assert [c.text for c in kept] == ["a", "b"]
    assert notes == []


def test_a_caption_past_the_end_is_dropped_not_clamped():
    # Clamping it to the end would show a caption the model meant for a moment
    # that never arrives.
    kept, notes = sanitize_captions([cap("late", 12, 2)], animation_duration=8)
    assert kept == []
    assert "at or past" in notes[0]


def test_a_negative_start_is_clamped_to_zero():
    kept, notes = sanitize_captions([cap("early", -3, 2)], animation_duration=8)
    assert kept[0].appear_at == 0
    assert "clamped to 0" in notes[0]


def test_a_caption_running_past_the_end_is_trimmed_not_dropped():
    kept, notes = sanitize_captions([cap("long", 6, 5)], animation_duration=8)
    assert kept[0].appear_at + kept[0].duration == pytest.approx(8)
    assert "trimmed" in notes[0]


def test_a_caption_trimmed_below_the_minimum_is_dropped():
    kept, _ = sanitize_captions([cap("squeezed", 7.8, 4)], animation_duration=8)
    assert kept == []


def test_too_short_a_duration_is_raised():
    kept, notes = sanitize_captions([cap("blink", 1, 0.1)], animation_duration=8)
    assert kept[0].duration == MIN_DURATION
    assert "raised" in notes[0]


def test_overlapping_captions_are_dropped():
    # Two captions on screen at once render on top of each other.
    kept, notes = sanitize_captions(
        [cap("first", 1, 3), cap("second", 2, 2)], animation_duration=10
    )
    assert [c.text for c in kept] == ["first"]
    assert "overlaps" in notes[0]


def test_captions_are_ordered_by_time():
    kept, _ = sanitize_captions(
        [cap("late", 6, 1), cap("early", 1, 1)], animation_duration=10
    )
    assert [c.text for c in kept] == ["early", "late"]


def test_the_caption_count_is_capped():
    raw = [cap(f"c{i}", i * 1.5, 1.0) for i in range(12)]
    kept, notes = sanitize_captions(raw, animation_duration=60, max_captions=3)
    assert len(kept) == 3
    assert any("cap" in n for n in notes)


def test_empty_and_malformed_captions_are_dropped():
    kept, notes = sanitize_captions(
        [cap("   ", 1, 2), {"text": "bad", "appearAt": "soon", "duration": 2}],
        animation_duration=8,
    )
    assert kept == []
    assert len(notes) == 2


def test_no_captions_is_valid():
    assert sanitize_captions([], animation_duration=8) == ([], [])
    assert sanitize_captions(None, animation_duration=8) == ([], [])


# --- language-aware number suffixes ---------------------------------------


def test_indonesian_gets_indonesian_abbreviations():
    # "1,2M" would read as 1.2 million to an English reader but means something
    # else in the Indonesian preset, where millions are Jt.
    assert suffixes_for("Indonesian").millions == "Jt"
    assert suffixes_for("Indonesian").thousands == "Rb"


def test_language_matching_is_case_insensitive():
    assert suffixes_for("indonesian").millions == "Jt"


def test_an_unknown_language_falls_back_to_english():
    assert suffixes_for("Klingon").millions == "M"
    assert suffixes_for("").millions == "M"


# --- compose stage ---------------------------------------------------------


def build_store(unit: str = "USD_billions") -> CanvasStore:
    store = CanvasStore("compose-test")
    store.allow_urls([SEARCHED])
    store.append_rows(
        [
            {
                "series": "OpenAI",
                "period_label": str(year),
                "raw_value": value,
                "raw_unit": unit,
                "source_url": SEARCHED,
            }
            for year, value in [(2023, 1.6), (2024, 3.7), (2025, 13.07)]
        ]
    )
    return store


def fake_response(tool_input: dict[str, Any] | None, stop_reason: str = "tool_use") -> Any:
    content = []
    if tool_input is not None:
        content.append(
            SimpleNamespace(type="tool_use", id="t1", name="build_chart", input=tool_input)
        )
    return SimpleNamespace(stop_reason=stop_reason, content=content)


@pytest.fixture
def stub(monkeypatch):
    calls: list[dict[str, Any]] = []

    def install(tool_input: dict[str, Any] | None, stop_reason: str = "tool_use"):
        def fake_create(messages, **kwargs):
            calls.append({"messages": messages, **kwargs})
            return fake_response(tool_input, stop_reason)

        monkeypatch.setattr(compose_module.llm, "create", fake_create)

    return SimpleNamespace(install=install, calls=calls)


PROPOSAL = {
    "title": "OpenAI revenue",
    "subtitle": "Annual, USD",
    "xLabel": "Year",
    "yLabel": "Revenue (USD)",
}


def run(store: CanvasStore, **kwargs) -> list[dict[str, Any]]:
    return list(
        run_compose(
            "OpenAI revenue",
            kwargs.pop("language", "English"),
            store=store,
            settings=SimpleNamespace(),
            **kwargs,
        )
    )


def config_from(events: list[dict[str, Any]]) -> dict[str, Any]:
    return next(e["data"]["config"] for e in events if e["event"] == "config")


def test_produces_a_renderer_shaped_config(stub):
    stub.install(PROPOSAL)
    config = config_from(run(build_store()))

    assert config["title"] == "OpenAI revenue"
    assert config["xAxisMode"] == "year"
    assert config["aspectRatio"] == "9:16"
    assert [s["name"] for s in config["series"]] == ["OpenAI"]


def test_the_tool_is_forced_so_the_model_cannot_answer_in_prose(stub):
    stub.install(PROPOSAL)
    run(build_store())
    assert stub.calls[0]["tool_choice"] == {"type": "tool", "name": "build_chart"}
    assert stub.calls[0]["tools"][0]["strict"] is True





def test_the_language_selects_the_number_suffixes(stub):
    stub.install(PROPOSAL)
    config = config_from(run(build_store(), language="Indonesian"))
    assert config["numberSuffixes"]["millions"] == "Jt"


def test_allow_negative_follows_the_data_not_the_model(stub):
    stub.install(PROPOSAL)
    assert config_from(run(build_store()))["allowNegative"] is False


def test_an_empty_canvas_fails_loudly(stub):
    stub.install(PROPOSAL)
    with pytest.raises(ComposeFailed, match="nothing to chart"):
        run(CanvasStore("empty"))


def test_a_missing_tool_call_fails_loudly(stub):
    stub.install(None, stop_reason="end_turn")
    with pytest.raises(ComposeFailed, match="did not call build_chart"):
        run(build_store())



def test_the_system_prompt_is_cacheable(stub):
    stub.install(PROPOSAL)
    run(build_store())
    assert stub.calls[0]["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_the_prompt_states_who_leads_at_each_period(stub):
    # The model reads values correctly but has been seen inverting the
    # comparison ("Tesla leads with 1.31M vs BYD's 1.86M"). Ranking is
    # arithmetic, so Python supplies it rather than asking for a derivation.
    store = CanvasStore("rank-test")
    store.allow_urls([SEARCHED])
    store.append_rows(
        [
            {"series": "Tesla", "period_label": "2022", "raw_value": 1313851,
             "raw_unit": "count", "source_url": SEARCHED},
            {"series": "BYD", "period_label": "2022", "raw_value": 1860000,
             "raw_unit": "count", "source_url": SEARCHED},
        ]
    )
    stub.install(PROPOSAL)
    run(store)
    prompt = stub.calls[0]["messages"][0]["content"]
    assert "Standing at each period" in prompt
    assert "2022: BYD 1,860,000 > Tesla 1,313,851" in prompt


# --- cross-boundary contract ----------------------------------------------


def test_the_config_matches_what_the_renderer_is_given_by_the_ui():
    """ChartConfig must carry exactly the keys DataInput.vue emits to onApply.

    The renderer consumes this shape directly, so a field added on either side
    without the other is a silent break — the chart just ignores it.
    """
    import re
    from pathlib import Path

    from app.schemas import ChartConfig

    source = Path(__file__).resolve().parents[2] / "frontend/src/components/DataInput.vue"
    if not source.exists():  # pragma: no cover - frontend not checked out
        pytest.skip("frontend sources not present")

    body = source.read_text(encoding="utf-8")
    apply_fn = re.search(r"function apply\(\)\s*\{.*?\n\}", body, re.S)
    assert apply_fn, "could not find apply() in DataInput.vue"
    emitted = set(re.findall(r"^\s{4}([a-zA-Z]+):", apply_fn.group(0), re.M))

    produced = set(ChartConfig(series=[]).model_dump(by_alias=True))
    assert emitted == produced, (
        f"only in the UI: {sorted(emitted - produced)}; "
        f"only in the backend: {sorted(produced - emitted)}"
    )


# --- strict guarantees shape, not sanity ----------------------------------





def test_text_fields_are_flattened_and_capped():
    from app.pipeline.compose import clean_text

    assert clean_text("Tesla  vs\nBYD", limit=120) == "Tesla vs BYD"
    assert clean_text("x" * 500, limit=20) == "x" * 20




# --- empty-caption retry ---------------------------------------------------







# --- currency is derived, not asked for -----------------------------------


def test_currency_is_not_part_of_the_tool_surface():
    # Asking for it meant asking the model to emit an empty string for a
    # required field whenever the data was counts; it repeatedly returned a
    # stray markup fragment instead. The canvas only accepts USD_* money units,
    # so the symbol is knowable without asking.
    from app.pipeline.compose import BUILD_CHART_TOOL

    properties = BUILD_CHART_TOOL["input_schema"]["properties"]
    assert set(properties) == {"title", "subtitle", "xLabel", "yLabel"}


def test_money_data_gets_a_symbol(stub):
    stub.install(PROPOSAL)
    assert config_from(run(build_store()))["currency"] == "$"


def test_count_data_gets_no_symbol(stub):
    stub.install(PROPOSAL)
    assert config_from(run(build_store(unit="count")))["currency"] == ""


def test_the_model_supplies_no_captions(stub):
    stub.install(PROPOSAL)
    assert config_from(run(build_store()))["captions"] == []


def test_model_strings_are_flattened_and_capped(stub):
    stub.install({**PROPOSAL, "title": "Tesla  vs\nBYD", "subtitle": "x" * 400})
    config = config_from(run(build_store()))
    assert config["title"] == "Tesla vs BYD"
    assert len(config["subtitle"]) == 160
