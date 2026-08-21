"""FastAPI application entry point.

Phase 1 is the skeleton: CORS for the Vite dev server and a health endpoint.
The research pipeline (§4) and the SSE chart endpoint (§5) land in later phases.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routes import health

app = FastAPI(title="video-vis AI chart agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
