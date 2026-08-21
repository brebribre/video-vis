"""SSE endpoint shape (§5), with the pipeline stubbed out."""

from __future__ import annotations

from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes import chart

client = TestClient(app)


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
def fake_research(monkeypatch):
    def install(events: list[dict[str, Any]] | Exception):
        def fake(*_args, **_kwargs) -> Iterator[dict[str, Any]]:
            if isinstance(events, Exception):
                raise events
            yield from events

        monkeypatch.setattr(chart, "run_research", fake)

    return install


def test_streams_events_as_server_sent_events(fake_research):
    fake_research(
        [
            {"event": "stage", "data": {"name": "research", "status": "start"}},
            {"event": "canvas", "data": {"rows": 2}},
        ]
    )
    response = client.post("/api/chart/generate", json={"topic": "x"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    names = [name for name, _ in parse_sse(response.text)]
    assert names == ["run", "stage", "canvas", "done"]


def test_the_run_id_comes_first_so_the_canvas_can_be_fetched(fake_research):
    fake_research([])
    events = parse_sse(client.post("/api/chart/generate", json={"topic": "x"}).text)
    assert events[0][0] == "run"
    assert "run_id" in events[0][1]


def test_a_pipeline_failure_becomes_an_error_event_not_a_dropped_stream(fake_research):
    # Raising mid-stream would leave the client hanging on a half-open response
    # with no way to tell a crash from a slow search.
    fake_research(RuntimeError("search exploded"))
    body = client.post("/api/chart/generate", json={"topic": "x"}).text
    events = dict(parse_sse(body))
    assert "error" in events
    assert "search exploded" in events["error"]
    assert "done" not in events, "a failed run must not also report success"


def test_buffering_is_disabled_so_events_arrive_as_they_happen(fake_research):
    fake_research([])
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
