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
from ..llm.anthropic_client import NoCredentials
from ..pipeline.research import Budget, run_research
from ..schemas import AspectRatio

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

    try:
        for message in run_research(
            request.topic,
            request.language,
            store=store,
            settings=get_settings(),
            budget=Budget(),
        ):
            yield _sse(message["event"], message["data"])
    except NoCredentials:
        yield _sse(
            "error",
            {"message": "ANTHROPIC_API_KEY is not set on the server.", "retryable": False},
        )
        return
    except Exception as exc:  # noqa: BLE001 - the stream must always close cleanly
        # A raised exception mid-stream would leave the client hanging on a
        # half-open response, so failures are delivered as an error event.
        yield _sse("error", {"message": f"{type(exc).__name__}: {exc}", "retryable": True})
        return

    # Stage 3 (compose) lands in Phase 4; until then the run ends after research.
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
