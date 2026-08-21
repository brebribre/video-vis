"""Stage 3 — compose the chart (§4.5).

A separate call from Stage 1 by necessity: `output_config.format` returns a 400
when citations are enabled, so the researching turn and the schema-guaranteed
turn cannot be the same request.

Everything the model returns is treated as a proposal. Captions are clamped,
currency is corrected against the data's actual dimension, and every other
`ChartConfig` field is filled server-side.
"""

from __future__ import annotations

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
from .captions import sanitize_captions

# `strict` guarantees the arguments validate exactly, so no defensive parsing of
# the tool input is needed. It requires additionalProperties:false and required
# on every object (§11).
BUILD_CHART_TOOL: dict[str, Any] = {
    "name": "build_chart",
    "description": (
        "Produce the final chart presentation. Call exactly once. Captions must "
        "be spaced across the animation and must not overlap."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short, concrete headline."},
            "subtitle": {"type": "string", "description": "Unit, span, or source qualifier."},
            "xLabel": {"type": "string"},
            "yLabel": {"type": "string", "description": "Must state the unit."},
            "currency": {
                "type": "string",
                "description": "Symbol for money values, or an empty string for counts.",
            },
            "currencyPosition": {"type": "string", "enum": ["prefix", "suffix"]},
            "captions": {
                "type": "array",
                "description": "Two to four typically; zero is valid.",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "appearAt": {
                            "type": "number",
                            "description": "Seconds from the start of the animation.",
                        },
                        "duration": {
                            "type": "number",
                            "description": "Seconds on screen.",
                        },
                    },
                    "required": ["text", "appearAt", "duration"],
                    "additionalProperties": False,
                },
            },
        },
        "required": [
            "title",
            "subtitle",
            "xLabel",
            "yLabel",
            "currency",
            "currencyPosition",
            "captions",
        ],
        "additionalProperties": False,
    },
}


class ComposeFailed(RuntimeError):
    pass


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
    if not series:
        raise ComposeFailed(
            "the canvas holds no usable rows, so there is nothing to chart"
        )

    response = llm.create(
        [
            {
                "role": "user",
                "content": compose_user_turn(
                    topic=topic,
                    language=language,
                    series=series,
                    animation_duration=animation_duration,
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
        max_tokens=4000,
    )

    proposal = _tool_input(response)
    if proposal is None:
        raise ComposeFailed(
            f"the model did not call build_chart (stop_reason={response.stop_reason})"
        )

    captions, notes = sanitize_captions(
        proposal.get("captions"), animation_duration=animation_duration
    )
    if notes:
        yield {"event": "notice", "data": {"captions": notes}}

    # A currency symbol against a delivery count is simply wrong, and the model
    # is more willing to fill the field than to leave it empty.
    currency = str(proposal.get("currency") or "")
    if dimension != "currency" and currency:
        currency = ""
        yield {
            "event": "notice",
            "data": {"currency": f"cleared: values are {dimension}, not money"},
        }

    config = ChartConfig(
        series=series,
        aspect_ratio=aspect_ratio,
        x_axis_mode=axis_mode,  # type: ignore[arg-type]
        title=str(proposal.get("title") or "").strip(),
        subtitle=str(proposal.get("subtitle") or "").strip(),
        x_label=str(proposal.get("xLabel") or "").strip(),
        y_label=str(proposal.get("yLabel") or "").strip(),
        currency=currency,
        currency_position=proposal.get("currencyPosition") or "prefix",  # type: ignore[arg-type]
        # Only true if the data actually goes negative; the renderer draws a
        # zero line when it is set.
        allow_negative=any(p.value < 0 for s in series for p in s.data),
        animation_duration=animation_duration,
        number_suffixes=suffixes_for(language),
        captions=captions,
    )

    yield {
        "event": "config",
        "data": {"config": config.model_dump(by_alias=True)},
    }
    yield {
        "event": "stage",
        "data": {
            "name": "compose",
            "status": "done",
            "captions": len(captions),
            "series": len(series),
        },
    }
