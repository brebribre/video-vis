"""Chart generation endpoints (§5).

Streams from the first event: a research loop takes a while, and a silent
spinner reads as a hang.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Iterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..canvas.store import CanvasStore
from ..config import RUNS_DIR, get_settings
from ..llm.anthropic_client import describe_error
from ..pipeline.compose import ComposeFailed, run_compose
from ..pipeline.research import Budget, run_research
from ..schemas import AspectRatio

NEWLINE = chr(10)

router = APIRouter()


class GenerateRequest(BaseModel):
    topic: str = Field(min_length=1)
    language: str = "English"
    aspect_ratio: AspectRatio = "9:16"
    animation_duration: float = 8


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _generate(request: GenerateRequest, run_id: str) -> Iterator[str]:
    store = CanvasStore(run_id, RUNS_DIR)
    yield _sse("run", {"run_id": run_id})

    summary: list[str] = []
    try:
        for message in run_research(
            request.topic,
            request.language,
            store=store,
            settings=get_settings(),
            budget=Budget(),
        ):
            if message["event"] == "token":
                # The researcher's closing prose gives compose context the raw
                # table cannot — which series moved, what could not be found.
                summary.append(str(message["data"].get("text", "")))
            yield _sse(message["event"], message["data"])

        for message in run_compose(
            request.topic,
            request.language,
            store=store,
            aspect_ratio=request.aspect_ratio,
            animation_duration=request.animation_duration,
            research_summary=NEWLINE.join(summary[-2:]),
            settings=get_settings(),
        ):
            yield _sse(message["event"], message["data"])
    except ComposeFailed as exc:
        # Retrying will not conjure data that research could not find.
        yield _sse("error", {"message": str(exc), "retryable": False})
        return
    except Exception as exc:  # noqa: BLE001 - the stream must always close cleanly
        # A raised exception mid-stream would leave the client hanging on a
        # half-open response, so failures are delivered as an error event.
        # `retryable` is classified per exception type: telling the user to
        # retry a 400 invites an identical failure at full cost.
        message, retryable = describe_error(exc)
        yield _sse("error", {"message": message, "retryable": retryable})
        return

    yield _sse("done", {})


@router.post("/chart/generate")
async def generate(request: GenerateRequest) -> StreamingResponse:
    run_id = uuid.uuid4().hex[:12]
    return StreamingResponse(
        _generate(request, run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Without this an intermediary can buffer the whole stream and
            # deliver it at the end, which defeats the point of streaming.
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/runs/{run_id}/canvas.csv")
async def download_canvas(run_id: str) -> FileResponse:
    if not run_id.isalnum():
        raise HTTPException(status_code=400, detail="invalid run id")
    path = RUNS_DIR / run_id / "canvas.csv"
    if not path.exists():
        raise HTTPException(status_code=404, detail="no canvas for that run")
    return FileResponse(path, media_type="text/csv", filename=f"canvas-{run_id}.csv")
