"""Runtime configuration, read from the environment (or backend/.env).

The DashScope API key lives here and nowhere else — it must never reach the
browser (§3 of AI_AGENT_REQUIREMENTS.md).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = BACKEND_DIR / ".runs"

# DashScope is region-scoped and model availability differs per region (§1.2).
DASHSCOPE_ENDPOINTS = {
    "intl": "https://dashscope-intl.aliyuncs.com/api/v1",
    "cn": "https://dashscope.aliyuncs.com/api/v1",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    dashscope_api_key: str = ""
    # "intl" (dashscope-intl.aliyuncs.com) or "cn" (dashscope.aliyuncs.com).
    dashscope_region: str = "intl"
    # Verify availability in the target region before pinning (§1.2).
    dashscope_model: str = "qwen3.7-plus"

    # Vite dev server origins allowed to call the API.
    cors_origins: str = "http://localhost:5175,http://127.0.0.1:5175"

    @property
    def base_url(self) -> str:
        try:
            return DASHSCOPE_ENDPOINTS[self.dashscope_region]
        except KeyError:
            raise ValueError(
                f"DASHSCOPE_REGION must be one of {sorted(DASHSCOPE_ENDPOINTS)}, "
                f"got {self.dashscope_region!r}"
            ) from None

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
