"""Canvas tool definitions and dispatch (§4.0).

These schemas are **module-level constants on purpose**. Tools render at
position 0 of the prompt, so building them per-run would change the cached
prefix on every request and defeat prompt caching entirely (§7).

They are deliberately *not* `strict: true`. Validation lives in the store, which
rejects a bad row with a reason the agent can act on ("cite a URL from your
search results") — far more useful than a schema-level refusal it cannot see.
"""

from __future__ import annotations

import json
from typing import Any

from .derive import UNITS
from .store import CanvasStore

_ROW_PROPERTIES: dict[str, Any] = {
    "series": {
        "type": "string",
        "description": "Entity the number belongs to, e.g. 'OpenAI'. Use one exact spelling throughout.",
    },
    "period_label": {
        "type": "string",
        "description": (
            "The period exactly as the source writes it — '2024', 'FY2024', "
            "'Q3 2025', '2024-06', 'Jun 2024'. Do not convert it."
        ),
    },
    "raw_value": {
        "type": "number",
        "description": "The number exactly as stated, before any unit conversion.",
    },
    "raw_unit": {
        "type": "string",
        "enum": sorted(UNITS),
        "description": "The unit the source states. 3.7 billion dollars is raw_value 3.7, raw_unit USD_billions.",
    },
    "source_url": {
        "type": "string",
        "description": "URL of the article this number came from. MUST be one your search returned.",
    },
    "source_title": {"type": "string", "description": "Title of the source article."},
    "cited_text": {
        "type": "string",
        "description": "Short verbatim quote from the source containing this number.",
    },
    "published_at": {
        "type": "string",
        "description": "Publication date, ISO 8601 where known. Used to settle disagreements between sources.",
    },
}

CANVAS_TOOLS: list[dict[str, Any]] = [
    {
        "name": "canvas_set_target",
        "description": (
            "Declare what this run is trying to collect: which series, and over "
            "which period range. Call this ONCE, early, as soon as you know what "
            "the topic needs — before searching. Until you do, the gap report can "
            "only compare what you have recorded against itself, so a series you "
            "have not started is not reported as missing and you may stop early "
            "believing the work is done."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "series": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Every entity to chart, e.g. ['OpenAI', 'Anthropic'].",
                },
                "start_period": {
                    "type": "string",
                    "description": "Earliest period wanted, e.g. '2023' or 'Q1 2024'.",
                },
                "end_period": {"type": "string", "description": "Latest period wanted."},
            },
            "required": ["series", "start_period", "end_period"],
        },
    },
    {
        "name": "canvas_read",
        "description": (
            "Read the data canvas and its gap report. Call this FIRST, and again "
            "after adding rows, to see what is still missing. The gap report lists "
            "missing periods per series, conflicts between sources, and rows needing "
            "attention. Work that list until it is empty."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "series": {"type": "string", "description": "Only rows for this series."},
                "status": {
                    "type": "string",
                    "description": "Only rows with this status, e.g. 'conflict'.",
                },
            },
        },
    },
    {
        "name": "canvas_append_rows",
        "description": (
            "Record datapoints you found. One row per (series, period) per source. "
            "Record only what the source literally states — never a figure you "
            "calculated, estimated, or remember. Rows are validated and each one "
            "comes back accepted or rejected with a reason; fix and retry rejects."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "rows": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": _ROW_PROPERTIES,
                        "required": [
                            "series",
                            "period_label",
                            "raw_value",
                            "raw_unit",
                            "source_url",
                        ],
                    },
                }
            },
            "required": ["rows"],
        },
    },
    {
        "name": "canvas_revise_row",
        "description": (
            "Correct an existing row after finding a better source. Use this to "
            "resolve a conflict rather than adding a third row."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"row_id": {"type": "string"}, **_ROW_PROPERTIES},
            "required": ["row_id"],
        },
    },
    {
        "name": "canvas_drop_row",
        "description": "Remove a row that proved wrong. A reason is required.",
        "input_schema": {
            "type": "object",
            "properties": {
                "row_id": {"type": "string"},
                "reason": {"type": "string", "description": "Why this row is wrong."},
            },
            "required": ["row_id", "reason"],
        },
    },
]

CANVAS_TOOL_NAMES = frozenset(tool["name"] for tool in CANVAS_TOOLS)


def dispatch(store: CanvasStore, name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    """Execute one canvas tool call. Never raises — errors are returned to the agent."""
    try:
        if name == "canvas_set_target":
            result = store.set_target(
                tool_input.get("series") or [],
                str(tool_input.get("start_period") or ""),
                str(tool_input.get("end_period") or ""),
            )
            return {
                "accepted": result.accepted,
                "reason": result.reason,
                "gap_report": store.gap_report(),
            }

        if name == "canvas_read":
            return store.read(
                series=tool_input.get("series") or None,
                status=tool_input.get("status") or None,
            )

        if name == "canvas_append_rows":
            rows = tool_input.get("rows") or []
            if not isinstance(rows, list):
                return {"error": "rows must be an array"}
            results = store.append_rows(rows)
            accepted = [r.row_id for r in results if r.accepted]
            rejected = [
                {"reason": r.reason, "input": r.input} for r in results if not r.accepted
            ]
            return {
                "accepted": accepted,
                "accepted_count": len(accepted),
                "rejected": rejected,
                "gap_report": store.gap_report(),
            }

        if name == "canvas_revise_row":
            row_id = tool_input.get("row_id")
            if not row_id:
                return {"error": "row_id is required"}
            changes = {k: v for k, v in tool_input.items() if k != "row_id"}
            result = store.revise_row(str(row_id), **changes)
            return {
                "accepted": result.accepted,
                "reason": result.reason,
                "gap_report": store.gap_report(),
            }

        if name == "canvas_drop_row":
            result = store.drop_row(
                str(tool_input.get("row_id") or ""),
                reason=str(tool_input.get("reason") or ""),
            )
            return {
                "accepted": result.accepted,
                "reason": result.reason,
                "gap_report": store.gap_report(),
            }

        return {"error": f"unknown tool {name!r}"}
    except Exception as exc:  # pragma: no cover - defensive
        # A crash here would strand the agent waiting for a tool_result, so the
        # failure is reported back to it instead of propagating.
        return {"error": f"{type(exc).__name__}: {exc}"}


def dispatch_json(store: CanvasStore, name: str, tool_input: dict[str, Any]) -> str:
    return json.dumps(dispatch(store, name, tool_input), ensure_ascii=False, default=str)
