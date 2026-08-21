"""Stage 1 loop control flow, driven by fake responses.

The behaviours that matter here are the ones that fail *silently* in production:
a dropped pause_turn truncates a run with no error, and splitting tool_results
across messages degrades the model's tool use over time. Both are pinned.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.canvas.store import CanvasStore
from app.pipeline import research
from app.pipeline.research import Budget, run_research

SEARCHED = "https://example.com/revenue-2024"


# --- fake response plumbing ------------------------------------------------


def text_block(text: str) -> Any:
    return SimpleNamespace(type="text", text=text, citations=None)


def search_block(*urls: str) -> Any:
    return SimpleNamespace(
        type="web_search_tool_result",
        content=[SimpleNamespace(url=u, title=f"title for {u}", page_age=None) for u in urls],
    )


def search_error_block(code: str) -> Any:
    # Server-tool errors come back HTTP 200 with an error OBJECT where the
    # result list would be — not an exception.
    return SimpleNamespace(
        type="web_search_tool_result", content=SimpleNamespace(error_code=code)
    )


class ToolUse(SimpleNamespace):
    def model_dump(self, **_: Any) -> dict[str, Any]:
        return {"type": "tool_use", "id": self.id, "name": self.name, "input": self.input}


def tool_use_block(tool_id: str, name: str, tool_input: dict[str, Any]) -> Any:
    return ToolUse(type="tool_use", id=tool_id, name=name, input=tool_input)


def response(stop_reason: str, content: list[Any]) -> Any:
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=content,
        usage=SimpleNamespace(input_tokens=100, output_tokens=50, cache_read_input_tokens=0),
    )


@pytest.fixture
def spy(monkeypatch):
    """Replace the API call with a scripted queue, recording every request."""
    calls: list[dict[str, Any]] = []
    queue: list[Any] = []

    def fake_create(messages, **kwargs):
        calls.append({"messages": [dict(m) for m in messages], **kwargs})
        return queue.pop(0)

    monkeypatch.setattr(research.llm, "create", fake_create)
    return SimpleNamespace(calls=calls, queue=queue)


def collect(store: CanvasStore, spy, **budget_kwargs) -> list[dict[str, Any]]:
    return list(
        run_research(
            "OpenAI revenue",
            "English",
            store=store,
            settings=SimpleNamespace(),
            budget=Budget(**budget_kwargs),
        )
    )


def events_of(events: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [e["data"] for e in events if e["event"] == name]


# --- pause_turn ------------------------------------------------------------


def test_pause_turn_is_resumed_not_treated_as_the_end(spy):
    store = CanvasStore("t")
    spy.queue.extend(
        [
            response("pause_turn", [search_block(SEARCHED)]),
            response("end_turn", [text_block("done")]),
        ]
    )
    events = collect(store, spy)

    assert len(spy.calls) == 2, "a paused turn must be re-sent, not silently ended"
    # Resumed by appending the assistant turn verbatim — never a 'Continue.' message.
    resumed = spy.calls[1]["messages"]
    assert resumed[-1]["role"] == "assistant"
    assert events_of(events, "stage")[-1]["stop_reason"] == "end_turn"


def test_pause_turn_respects_the_continuation_cap(spy):
    store = CanvasStore("t")
    spy.queue.extend([response("pause_turn", []) for _ in range(10)])
    events = collect(store, spy, max_continuations=2, max_iterations=10)

    assert len(spy.calls) == 3, "initial call plus two continuations"
    assert events_of(events, "stage")[-1]["stop_reason"] == "continuation_limit"


# --- tool results ----------------------------------------------------------


def test_all_tool_results_go_back_in_one_user_message(spy):
    # Splitting them across messages trains the model out of parallel tool use.
    store = CanvasStore("t")
    store.allow_urls([SEARCHED])
    spy.queue.extend(
        [
            response(
                "tool_use",
                [
                    tool_use_block("a", "canvas_read", {}),
                    tool_use_block(
                        "b",
                        "canvas_append_rows",
                        {
                            "rows": [
                                {
                                    "series": "OpenAI",
                                    "period_label": "2024",
                                    "raw_value": 3.7,
                                    "raw_unit": "USD_billions",
                                    "source_url": SEARCHED,
                                }
                            ]
                        },
                    ),
                ],
            ),
            response("end_turn", [text_block("done")]),
        ]
    )
    collect(store, spy)

    user_turns = [m for m in spy.calls[1]["messages"] if m["role"] == "user"]
    tool_results = [
        block
        for turn in user_turns
        if isinstance(turn["content"], list)
        for block in turn["content"]
        if block.get("type") == "tool_result"
    ]
    assert len(tool_results) == 2
    assert len([t for t in user_turns if isinstance(t["content"], list)]) == 1


def test_tool_results_reference_their_tool_use_ids(spy):
    store = CanvasStore("t")
    spy.queue.extend(
        [
            response("tool_use", [tool_use_block("call-1", "canvas_read", {})]),
            response("end_turn", [text_block("done")]),
        ]
    )
    collect(store, spy)
    payload = spy.calls[1]["messages"][-1]["content"][0]
    assert payload["tool_use_id"] == "call-1"


def test_an_unknown_tool_is_reported_back_as_an_error(spy):
    # Leaving a tool_use unanswered strands the conversation; the API rejects
    # the next turn for a missing tool_result.
    store = CanvasStore("t")
    spy.queue.extend(
        [
            response("tool_use", [tool_use_block("x", "not_a_tool", {})]),
            response("end_turn", [text_block("done")]),
        ]
    )
    collect(store, spy)
    payload = spy.calls[1]["messages"][-1]["content"][0]
    assert payload["is_error"] is True


def test_assistant_tool_use_blocks_survive_into_the_next_request(spy):
    store = CanvasStore("t")
    spy.queue.extend(
        [
            response("tool_use", [tool_use_block("keep-me", "canvas_read", {})]),
            response("end_turn", [text_block("done")]),
        ]
    )
    collect(store, spy)
    assistant = [m for m in spy.calls[1]["messages"] if m["role"] == "assistant"][-1]
    assert assistant["content"][0]["id"] == "keep-me"


# --- §4.2 URL harvesting ---------------------------------------------------


def test_search_urls_are_allowed_before_tools_run_in_the_same_turn(spy):
    # The model routinely searches and appends in one turn. If harvesting ran
    # after tool dispatch, that row would be rejected as unverified.
    store = CanvasStore("t")
    spy.queue.extend(
        [
            response(
                "tool_use",
                [
                    search_block(SEARCHED),
                    tool_use_block(
                        "a",
                        "canvas_append_rows",
                        {
                            "rows": [
                                {
                                    "series": "OpenAI",
                                    "period_label": "2024",
                                    "raw_value": 3.7,
                                    "raw_unit": "USD_billions",
                                    "source_url": SEARCHED,
                                }
                            ]
                        },
                    ),
                ],
            ),
            response("end_turn", [text_block("done")]),
        ]
    )
    collect(store, spy)
    assert len(store.rows) == 1
    assert store.rows[0].status == "ok"


def test_sources_are_only_emitted_once(spy):
    store = CanvasStore("t")
    spy.queue.extend(
        [
            response("tool_use", [search_block(SEARCHED), tool_use_block("a", "canvas_read", {})]),
            response("end_turn", [search_block(SEARCHED), text_block("done")]),
        ]
    )
    events = collect(store, spy)
    emitted = [s for batch in events_of(events, "sources") for s in batch["sources"]]
    assert len(emitted) == 1, "the same URL must not be streamed to the UI twice"


def test_server_tool_errors_surface_without_raising(spy):
    store = CanvasStore("t")
    spy.queue.extend(
        [
            response("end_turn", [search_error_block("url_not_in_prior_context")]),
        ]
    )
    events = collect(store, spy)
    assert events_of(events, "notice") == [{"tool_error": "url_not_in_prior_context"}]


# --- budgets ---------------------------------------------------------------


def test_the_iteration_cap_stops_a_runaway_loop(spy):
    store = CanvasStore("t")
    spy.queue.extend([response("tool_use", [tool_use_block(f"t{i}", "canvas_read", {})]) for i in range(20)])
    events = collect(store, spy, max_iterations=4)

    assert len(spy.calls) == 4
    assert events_of(events, "stage")[-1]["stop_reason"] == "iteration_limit"


def test_the_token_budget_stops_the_loop(spy):
    store = CanvasStore("t")
    spy.queue.extend([response("tool_use", [tool_use_block(f"t{i}", "canvas_read", {})]) for i in range(20)])
    events = collect(store, spy, max_total_tokens=200, max_iterations=20)

    # 150 tokens per fake response, so the second call crosses the ceiling.
    assert len(spy.calls) == 2
    assert events_of(events, "stage")[-1]["stop_reason"] == "token_budget"


def test_search_max_uses_is_passed_to_the_tool(spy):
    store = CanvasStore("t")
    spy.queue.append(response("end_turn", [text_block("done")]))
    collect(store, spy, max_search_uses=3)

    search_tool = next(t for t in spy.calls[0]["tools"] if t["name"] == "web_search")
    assert search_tool["max_uses"] == 3


# --- prompt caching (§7) ---------------------------------------------------


def test_the_system_prompt_carries_a_cache_breakpoint(spy):
    store = CanvasStore("t")
    spy.queue.append(response("end_turn", [text_block("done")]))
    collect(store, spy)
    assert spy.calls[0]["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_tool_definitions_are_identical_across_runs(spy):
    # Tools render at position 0, so any per-run variation would invalidate the
    # cached prefix on every request.
    store = CanvasStore("t")
    spy.queue.extend([response("end_turn", [text_block("a")]), response("end_turn", [text_block("b")])])
    collect(store, spy)
    collect(CanvasStore("t2"), spy)
    assert spy.calls[0]["tools"] == spy.calls[1]["tools"]


def test_usage_is_reported_on_completion(spy):
    store = CanvasStore("t")
    spy.queue.append(response("end_turn", [text_block("done")]))
    events = collect(store, spy)
    usage = events_of(events, "stage")[-1]["usage"]
    assert usage["input_tokens"] == 100
    assert usage["output_tokens"] == 50


# --- canvas progress -------------------------------------------------------


def test_canvas_progress_is_streamed_after_each_tool_turn(spy):
    store = CanvasStore("t")
    store.allow_urls([SEARCHED])
    spy.queue.extend(
        [
            response(
                "tool_use",
                [
                    tool_use_block(
                        "a",
                        "canvas_append_rows",
                        {
                            "rows": [
                                {
                                    "series": "OpenAI",
                                    "period_label": "2024",
                                    "raw_value": 3.7,
                                    "raw_unit": "USD_billions",
                                    "source_url": SEARCHED,
                                }
                            ]
                        },
                    )
                ],
            ),
            response("end_turn", [text_block("done")]),
        ]
    )
    events = collect(store, spy)
    [canvas] = events_of(events, "canvas")
    assert canvas["rows"] == 1
    assert canvas["series"] == ["OpenAI"]


# --- server-tool container -------------------------------------------------


def container_response(stop_reason: str, content: list[Any], cid: str | None) -> Any:
    resp = response(stop_reason, content)
    resp.container = SimpleNamespace(id=cid) if cid else None
    return resp


def test_the_server_tool_container_is_carried_into_later_turns(spy):
    # The _20260209 web tools filter results through code execution, so once a
    # container exists every later request must pass it back. Dropping it is a
    # hard 400: "container_id is required when there are pending tool uses".
    store = CanvasStore("t")
    spy.queue.extend(
        [
            container_response("tool_use", [tool_use_block("a", "canvas_read", {})], "cntr_1"),
            container_response("end_turn", [text_block("done")], None),
        ]
    )
    collect(store, spy)

    assert "container" not in spy.calls[0], "no container exists before the first response"
    assert spy.calls[1]["container"] == "cntr_1"


def test_the_container_stays_set_once_opened(spy):
    # Later responses may omit it; the conversation still needs it.
    store = CanvasStore("t")
    spy.queue.extend(
        [
            container_response("tool_use", [tool_use_block("a", "canvas_read", {})], "cntr_1"),
            container_response("tool_use", [tool_use_block("b", "canvas_read", {})], None),
            container_response("end_turn", [text_block("done")], None),
        ]
    )
    collect(store, spy)
    assert spy.calls[1]["container"] == "cntr_1"
    assert spy.calls[2]["container"] == "cntr_1"
