"""FastAPI application entry point.

CORS for the Vite dev server, a health endpoint, and the SSE chart endpoint
that drives the research loop (§4.1) and serves per-run canvases (§5).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routes import chart, health

app = FastAPI(title="video-vis AI chart agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(chart.router, prefix="/api")
