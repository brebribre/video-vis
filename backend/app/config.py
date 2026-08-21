"""Runtime configuration, read from the environment (or backend/.env).

The Anthropic API key lives here and nowhere else — it must never reach the
browser (§3 of AI_AGENT_REQUIREMENTS.md).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = BACKEND_DIR / ".runs"

# Models that support the _20260209 server-tool variants (web search + web fetch
# with dynamic filtering). Older models fall back to basic web_search_20250305,
# which this app does not currently handle — see §11.
MODELS_WITH_MODERN_SEARCH = frozenset(
    {
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-sonnet-5",
        "claude-sonnet-4-6",
    }
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str = ""
    # Sonnet 5 supports web_search_20260209 and is materially cheaper than Opus
    # for a loop that resends its conversation every iteration (§7).
    anthropic_model: str = "claude-sonnet-5"
    # low | medium | high | xhigh | max — goes inside output_config, not top level.
    anthropic_effort: str = "high"

    # Vite dev server origins allowed to call the API.
    cors_origins: str = "http://localhost:5175,http://127.0.0.1:5175"

    @property
    def supports_modern_search(self) -> bool:
        return self.anthropic_model in MODELS_WITH_MODERN_SEARCH

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
