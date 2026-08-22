"""Stage 3 — compose the chart (§4.5).

A separate call from Stage 1 by necessity: `output_config.format` returns a 400
when citations are enabled, so the researching turn and the schema-guaranteed
turn cannot be the same request.

The model writes language only — title, subtitle, axis labels. Everything else
on the `ChartConfig` is filled server-side, and every string it returns is
scrubbed before use.

Captions are **not** requested from the model at present. `pipeline/captions.py`
still holds the sanitiser for when they are re-enabled; users can add captions
by hand in the UI meanwhile.
"""

from __future__ import annotations

import re
from typing import Any, Iterator

from ..canvas.store import CanvasStore
from ..config import Settings, get_settings
from ..llm import anthropic_client as llm
from ..prompts.compose import COMPOSE_SYSTEM, compose_user_turn
from ..schemas import (
    NUMBER_SUFFIX_PRESETS,
    AspectRatio,
    ChartConfig,
    NumberSuffixes,
)

# `strict` guarantees the arguments validate against the schema. It does not
# guarantee the *contents* of a string — see clean_text below.
#
# The surface is deliberately small. An earlier version also asked for
# `currency`, which meant asking the model to emit an empty string for a
# required field whenever the data was counts; it repeatedly returned a stray
# markup fragment instead. The canvas only accepts USD_* money units, so the
# symbol is knowable without asking.
BUILD_CHART_TOOL: dict[str, Any] = {
    "name": "build_chart",
    "description": "Write the chart's title, subtitle and axis labels. Call exactly once.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short, concrete headline."},
            "subtitle": {
                "type": "string",
                "description": "Unit, span, or source qualifier.",
            },
            "xLabel": {"type": "string", "description": "X axis label."},
            "yLabel": {"type": "string", "description": "Y axis label. Must state the unit."},
        },
        "required": ["title", "subtitle", "xLabel", "yLabel"],
        "additionalProperties": False,
    },
}

# Extend if canvas.derive.UNITS ever carries a non-USD money unit.
_SYMBOL_FOR_DIMENSION = {"currency": "$"}

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


# A single point is not a line. Below this there is nothing to animate, so the
# run stops here rather than spending a compose call on it (§10.1).
MIN_POINTS_FOR_CHART = 2


class ComposeFailed(RuntimeError):
    """Raised before any API call when the canvas cannot make a chart."""


def explain_unchartable(store: CanvasStore, points: int) -> str:
    """Say what was found and why it is not enough, not just that it failed.

    "No usable rows" on its own leaves the user with no idea whether the topic
    was wrong, the sources were unusable, or something broke.
    """
    report = store.gap_report()
    target = report.get("target")
    attention = report.get("needs_attention") or []

    if points == 0:
        head = "The research finished without recording any usable datapoints."
    else:
        head = (
            f"Only {points} usable datapoint was recorded — a line chart needs at "
            f"least {MIN_POINTS_FOR_CHART}."
        )

    detail: list[str] = []
    if target:
        wanted = ", ".join(target["series"])
        detail.append(f"Looking for {wanted} over {target['start']}–{target['end']}.")
    if attention:
        reasons = sorted({row["status"] for row in attention})
        detail.append(
            f"{len(attention)} row(s) were rejected: {', '.join(reasons)}."
        )
    if store.rows and not points:
        detail.append("Every recorded row failed validation.")

    tail = (
        f"Try a more specific topic, or a period where the figures are published. "
        f"The raw canvas for this run is at /api/runs/{store.run_id}/canvas.csv."
    )
    return " ".join([head, *detail, tail])


def clean_text(value: object, *, limit: int) -> str:
    """Flatten and cap a model-supplied string.

    `strict: true` guarantees the argument *shape*, not that a string is sane —
    a live run returned a field containing a stray markup fragment, and these
    strings are drawn straight onto the chart.
    """
    text = _CONTROL.sub(" ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def suffixes_for(language: str) -> NumberSuffixes:
    """Match the abbreviations to the output language.

    An Indonesian chart reading "1,2M" where it means 1.2 million is wrong — the
    preset renders it "1,2Jt" (§4.5).
    """
    key = (language or "").strip().lower()
    for name, preset in NUMBER_SUFFIX_PRESETS.items():
        if name.lower() == key:
            return NumberSuffixes(**preset)
    return NumberSuffixes(**NUMBER_SUFFIX_PRESETS["English"])


def _tool_input(response: Any) -> dict[str, Any] | None:
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "tool_use" and block.name == "build_chart":
            return dict(block.input or {})
    return None


def run_compose(
    topic: str,
    language: str,
    *,
    store: CanvasStore,
    aspect_ratio: AspectRatio = "9:16",
    animation_duration: float = 8,
    research_summary: str = "",
    settings: Settings | None = None,
) -> Iterator[dict[str, Any]]:
    """Turn the finalised canvas into a ChartConfig, yielding SSE-shaped events."""
    settings = settings or get_settings()

    yield {"event": "stage", "data": {"name": "compose", "status": "start"}}

    series, axis_mode, dimension = store.finalize()
    points = sum(len(s.data) for s in series)
    if points < MIN_POINTS_FOR_CHART:
        # Raised before llm.create, so an unchartable run costs nothing.
        raise ComposeFailed(explain_unchartable(store, points))

    response = llm.create(
        [
            {
                "role": "user",
                "content": compose_user_turn(
                    topic=topic,
                    language=language,
                    series=series,
                    dimension=dimension,
                    axis_mode=axis_mode,
                    research_summary=research_summary,
                ),
            }
        ],
        settings=settings,
        system=[
            {
                "type": "text",
                "text": COMPOSE_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[BUILD_CHART_TOOL],
        tool_choice={"type": "tool", "name": "build_chart"},
        max_tokens=2000,
    )

    proposal = _tool_input(response)
    if proposal is None:
        raise ComposeFailed(
            f"the model did not call build_chart (stop_reason={response.stop_reason})"
        )

    config = ChartConfig(
        series=series,
        aspect_ratio=aspect_ratio,
        x_axis_mode=axis_mode,  # type: ignore[arg-type]
        title=clean_text(proposal.get("title"), limit=120),
        subtitle=clean_text(proposal.get("subtitle"), limit=160),
        x_label=clean_text(proposal.get("xLabel"), limit=60),
        y_label=clean_text(proposal.get("yLabel"), limit=60),
        # Derived, not asked for: a "$" against a delivery count is simply wrong.
        currency=_SYMBOL_FOR_DIMENSION.get(dimension, ""),
        currency_position="prefix",
        # Only true if the data actually goes negative; the renderer draws a
        # zero line when it is set.
        allow_negative=any(p.value < 0 for s in series for p in s.data),
        animation_duration=animation_duration,
        number_suffixes=suffixes_for(language),
        captions=[],
    )

    yield {"event": "config", "data": {"config": config.model_dump(by_alias=True)}}
    yield {
        "event": "stage",
        "data": {"name": "compose", "status": "done", "series": len(series)},
    }
