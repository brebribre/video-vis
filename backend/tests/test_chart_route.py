"""SSE endpoint shape (§5), with both pipeline stages stubbed out."""

from __future__ import annotations

from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.pipeline.compose import ComposeFailed
from app.routes import chart

client = TestClient(app)

CONFIG_EVENT = {"event": "config", "data": {"config": {"title": "t", "series": []}}}


def parse_sse(body: str) -> list[tuple[str, str]]:
    events: list[tuple[str, str]] = []
    name = None
    for line in body.splitlines():
        if line.startswith("event: "):
            name = line[7:]
        elif line.startswith("data: ") and name:
            events.append((name, line[6:]))
            name = None
    return events


@pytest.fixture
def pipeline(monkeypatch):
    """Stub both stages. Either may be a list of events or an exception."""

    def install(research: Any = None, compose: Any = None):
        def make(events: Any):
            def fake(*_args, **_kwargs) -> Iterator[dict[str, Any]]:
                if isinstance(events, Exception):
                    raise events
                yield from (events or [])

            return fake

        monkeypatch.setattr(chart, "run_research", make(research))
        monkeypatch.setattr(chart, "run_compose", make(compose))

    return install


def test_streams_both_stages_as_server_sent_events(pipeline):
    pipeline(
        research=[
            {"event": "stage", "data": {"name": "research", "status": "start"}},
            {"event": "canvas", "data": {"rows": 2}},
        ],
        compose=[CONFIG_EVENT],
    )
    response = client.post("/api/chart/generate", json={"topic": "x"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    names = [name for name, _ in parse_sse(response.text)]
    assert names == ["run", "stage", "canvas", "config", "done"]


def test_the_run_id_comes_first_so_the_canvas_can_be_fetched(pipeline):
    pipeline()
    events = parse_sse(client.post("/api/chart/generate", json={"topic": "x"}).text)
    assert events[0][0] == "run"
    assert "run_id" in events[0][1]


def test_research_prose_is_passed_to_compose(monkeypatch):
    # The closing summary tells compose which series moved and what could not be
    # found — context the raw table does not carry.
    seen: dict[str, Any] = {}

    def fake_research(*_a, **_k):
        yield {"event": "token", "data": {"text": "BYD overtook Tesla in 2023."}}

    def fake_compose(*_a, **kwargs):
        seen.update(kwargs)
        yield CONFIG_EVENT

    monkeypatch.setattr(chart, "run_research", fake_research)
    monkeypatch.setattr(chart, "run_compose", fake_compose)
    client.post("/api/chart/generate", json={"topic": "x"})

    assert "BYD overtook Tesla" in seen["research_summary"]


def test_request_settings_reach_compose(monkeypatch):
    seen: dict[str, Any] = {}

    def fake_compose(*_a, **kwargs):
        seen.update(kwargs)
        yield CONFIG_EVENT

    monkeypatch.setattr(chart, "run_research", lambda *a, **k: iter(()))
    monkeypatch.setattr(chart, "run_compose", fake_compose)
    client.post(
        "/api/chart/generate",
        json={"topic": "x", "aspect_ratio": "4:5", "animation_duration": 12},
    )

    assert seen["aspect_ratio"] == "4:5"
    assert seen["animation_duration"] == 12


def test_a_pipeline_failure_becomes_an_error_event_not_a_dropped_stream(pipeline):
    # Raising mid-stream would leave the client hanging on a half-open response
    # with no way to tell a crash from a slow search.
    pipeline(research=RuntimeError("search exploded"))
    events = dict(parse_sse(client.post("/api/chart/generate", json={"topic": "x"}).text))
    assert "error" in events
    assert "search exploded" in events["error"]
    assert "done" not in events, "a failed run must not also report success"


def test_an_unchartable_canvas_reports_a_non_retryable_error(pipeline):
    # Retrying will not conjure data that research could not find.
    pipeline(compose=ComposeFailed("the canvas holds no usable rows"))
    events = dict(parse_sse(client.post("/api/chart/generate", json={"topic": "x"}).text))
    assert "no usable rows" in events["error"]
    assert '"retryable": false' in events["error"]
    assert "done" not in events


def test_buffering_is_disabled_so_events_arrive_as_they_happen(pipeline):
    pipeline()
    response = client.post("/api/chart/generate", json={"topic": "x"})
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"


def test_a_topic_is_required():
    assert client.post("/api/chart/generate", json={"topic": ""}).status_code == 422
    assert client.post("/api/chart/generate", json={}).status_code == 422


def test_canvas_download_404s_for_an_unknown_run():
    assert client.get("/api/runs/deadbeef/canvas.csv").status_code == 404


def test_canvas_download_rejects_a_path_traversal_attempt():
    # run_id lands in a filesystem path, so it must never escape RUNS_DIR.
    assert client.get("/api/runs/..%2f..%2fetc/canvas.csv").status_code in {400, 404}


def test_canvas_download_returns_the_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(chart, "RUNS_DIR", tmp_path)
    run_dir = tmp_path / "abc123"
    run_dir.mkdir()
    (run_dir / "canvas.csv").write_text("row_id,series\nr1,OpenAI\n", encoding="utf-8")

    response = client.get("/api/runs/abc123/canvas.csv")
    assert response.status_code == 200
    assert "OpenAI" in response.text


# --- §6 typed error classification ----------------------------------------


def test_a_bad_request_is_reported_as_not_retryable(pipeline):
    # Telling the user to retry a 400 invites an identical failure at full cost.
    import httpx
    import anthropic

    exc = anthropic.BadRequestError(
        "container_id is required",
        response=httpx.Response(400, request=httpx.Request("POST", "https://x")),
        body=None,
    )
    pipeline(research=exc)
    events = dict(parse_sse(client.post("/api/chart/generate", json={"topic": "x"}).text))
    assert '"retryable": false' in events["error"]


def test_a_rate_limit_is_reported_as_retryable(pipeline):
    import httpx
    import anthropic

    exc = anthropic.RateLimitError(
        "slow down",
        response=httpx.Response(429, request=httpx.Request("POST", "https://x")),
        body=None,
    )
    pipeline(research=exc)
    events = dict(parse_sse(client.post("/api/chart/generate", json={"topic": "x"}).text))
    assert '"retryable": true' in events["error"]
    assert "Rate limited" in events["error"]


def test_a_missing_key_is_reported_as_not_retryable(pipeline):
    from app.llm.anthropic_client import NoCredentials

    pipeline(research=NoCredentials("ANTHROPIC_API_KEY is not set"))
    events = dict(parse_sse(client.post("/api/chart/generate", json={"topic": "x"}).text))
    assert "ANTHROPIC_API_KEY" in events["error"]
    assert '"retryable": false' in events["error"]
