"""Stage 1 — the research loop (§4.1).

A manual agentic loop, not the SDK tool runner: the runner does not auto-resume
`pause_turn`, and in Python it cannot be resumed mid-loop, so a paused turn
would silently end the run with a truncated result. With server tools in the mix
`pause_turn` is routine, so it is handled explicitly here.

Yields plain dict events for the SSE layer, so the pipeline stays testable
without HTTP.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

from ..canvas.store import CanvasStore
from ..canvas.tools import CANVAS_TOOL_NAMES, CANVAS_TOOLS, dispatch_json
from ..config import Settings, get_settings
from ..llm import anthropic_client as llm
from ..prompts.research import RESEARCH_SYSTEM, research_user_turn


@dataclass
class Budget:
    """Bounds on the loop. A vague topic can otherwise chase gaps forever (§4.1)."""

    max_iterations: int = 12
    max_search_uses: int = 12
    max_continuations: int = llm.MAX_CONTINUATIONS
    max_output_tokens: int = 16000
    # Total input+output across the run. None disables the ceiling.
    max_total_tokens: int | None = 600_000


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        self.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        self.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0


def _system_blocks() -> list[dict[str, Any]]:
    """System prompt as a cacheable block.

    The breakpoint sits on the last system block, which caches tools + system
    together — they render before messages, so both are covered (§7).
    """
    return [
        {
            "type": "text",
            "text": RESEARCH_SYSTEM,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def _blocks_to_params(content: Any) -> list[dict[str, Any]]:
    """Assistant content back into request shape, preserving every block.

    Tool-use and server-tool blocks must survive intact or the next turn is
    rejected for referencing a tool_use the conversation no longer contains.
    """
    out: list[dict[str, Any]] = []
    for block in content or []:
        if hasattr(block, "model_dump"):
            out.append(block.model_dump(exclude_none=True))
        elif isinstance(block, dict):
            out.append(block)
    return out


def run_research(
    topic: str,
    language: str,
    *,
    store: CanvasStore,
    settings: Settings | None = None,
    budget: Budget | None = None,
) -> Iterator[dict[str, Any]]:
    """Drive the loop, yielding SSE-shaped events."""
    settings = settings or get_settings()
    budget = budget or Budget()
    usage = Usage()

    tools = [*llm.web_tools(max_uses=budget.max_search_uses), *CANVAS_TOOLS]
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": research_user_turn(topic, language)}
    ]

    yield {"event": "stage", "data": {"name": "research", "status": "start"}}

    seen_urls: set[str] = set()
    continuations = 0
    stop_reason = "unknown"
    container: str | None = None

    for _ in range(budget.max_iterations):
        extra: dict[str, Any] = {"container": container} if container else {}
        response = llm.create(
            messages,
            settings=settings,
            system=_system_blocks(),
            tools=tools,
            max_tokens=budget.max_output_tokens,
            **extra,
        )
        usage.add(response)
        # Sticky for the rest of the run once the server tools open one.
        container = llm.container_id(response) or container
        stop_reason = response.stop_reason

        # Harvest source URLs *before* any tool runs, so rows appended in this
        # same turn can cite what this turn just found (§4.2).
        found = llm.search_results(response)
        if found:
            added = store.allow_urls(r["url"] for r in found)
            fresh = [r for r in found if r["url"] not in seen_urls]
            seen_urls.update(r["url"] for r in found)
            if fresh:
                yield {"event": "sources", "data": {"sources": fresh, "newly_allowed": added}}

        for code in llm.search_errors(response):
            # Server-tool failures arrive as HTTP 200 with an error object, not
            # an exception. url_not_in_prior_context is the common one: the
            # model tried to fetch a URL search had not returned.
            yield {"event": "notice", "data": {"tool_error": code}}

        text = llm.message_text(response)
        if text.strip():
            yield {"event": "token", "data": {"text": text}}

        if stop_reason == "pause_turn":
            if continuations >= budget.max_continuations:
                stop_reason = "continuation_limit"
                break
            continuations += 1
            messages.append({"role": "assistant", "content": _blocks_to_params(response.content)})
            continue

        if stop_reason != "tool_use":
            break

        # Every tool_result for one assistant turn goes back in a SINGLE user
        # message — splitting them trains the model out of parallel tool calls.
        results: list[dict[str, Any]] = []
        for block in response.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            if block.name not in CANVAS_TOOL_NAMES:
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"unknown tool {block.name!r}",
                        "is_error": True,
                    }
                )
                continue
            payload = dispatch_json(store, block.name, dict(block.input or {}))
            results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": payload}
            )

        if not results:
            break

        messages.append({"role": "assistant", "content": _blocks_to_params(response.content)})
        messages.append({"role": "user", "content": results})

        store.persist()
        report = store.gap_report()
        yield {
            "event": "canvas",
            "data": {
                "rows": len(store.rows),
                "series": report.get("series", []),
                "range": report.get("range"),
                "missing": report.get("missing", []),
                "conflicts": len(report.get("conflicts", [])),
                "needs_attention": len(report.get("needs_attention", [])),
            },
        }

        if budget.max_total_tokens is not None and usage.total >= budget.max_total_tokens:
            stop_reason = "token_budget"
            break
    else:
        stop_reason = "iteration_limit"

    store.persist()
    yield {
        "event": "stage",
        "data": {
            "name": "research",
            "status": "done",
            "stop_reason": stop_reason,
            "rows": len(store.rows),
            "usage": {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_read_input_tokens": usage.cache_read_tokens,
            },
        },
    }
