"""Thin wrapper over the **native** DashScope API.

Why native and not the OpenAI-compatible endpoint: the compatible protocol does
not return search sources, and §4.2's anti-fabrication guard depends on knowing
which URLs were actually retrieved. See §1.2.
"""

from __future__ import annotations

from typing import Any

import dashscope
from dashscope import Generation

from ..config import Settings, get_settings

# Search options for a Stage 1 SEARCH turn (§4.1). `forced_search` stops the
# model answering from parametric memory, which would yield numbers with no
# `search_results` behind them.
SEARCH_OPTIONS: dict[str, Any] = {
    "enable_source": True,
    "enable_citation": True,
    "citation_format": "[<number>]",
    "forced_search": True,
    "search_strategy": "agent",
}


class DashScopeError(RuntimeError):
    """A non-200 response from DashScope, carrying its code and message."""

    def __init__(self, status_code: int, code: str | None, message: str) -> None:
        super().__init__(f"DashScope {status_code} {code or ''}: {message}".strip())
        self.status_code = status_code
        self.code = code


def _configure(settings: Settings) -> None:
    if not settings.dashscope_api_key:
        raise DashScopeError(0, "no_api_key", "DASHSCOPE_API_KEY is not set")
    dashscope.api_key = settings.dashscope_api_key
    dashscope.base_http_api_url = settings.base_url


def generate(
    messages: list[dict[str, Any]],
    *,
    settings: Settings | None = None,
    model: str | None = None,
    enable_search: bool = False,
    search_options: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    response_format: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Any:
    """One non-streaming native `Generation.call`, with errors raised not returned."""
    settings = settings or get_settings()
    _configure(settings)

    params: dict[str, Any] = {
        "model": model or settings.dashscope_model,
        "messages": messages,
        "result_format": "message",
        **kwargs,
    }
    if enable_search:
        params["enable_search"] = True
        params["search_options"] = search_options or SEARCH_OPTIONS
    if tools is not None:
        params["tools"] = tools
        params.setdefault("tool_choice", "auto")
    if response_format is not None:
        params["response_format"] = response_format

    response = Generation.call(**params)
    if response.status_code != 200:
        raise DashScopeError(
            response.status_code,
            getattr(response, "code", None),
            getattr(response, "message", ""),
        )
    return response


def search_results(response: Any) -> list[dict[str, Any]]:
    """The retrieved result list, or `[]` when the model did not search.

    Shape per result: `{index, title, url, site_name, icon}` (§11).
    """
    search_info = getattr(response.output, "search_info", None) or {}
    return list(search_info.get("search_results") or [])


def message_text(response: Any) -> str:
    """Assistant text from a `result_format="message"` response."""
    choices = getattr(response.output, "choices", None) or []
    if not choices:
        return getattr(response.output, "text", "") or ""
    return choices[0]["message"].get("content") or ""
