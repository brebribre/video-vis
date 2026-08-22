"""Thin wrapper over the Anthropic Messages API.

Everything the research loop needs from the provider lives here: the server-side
web tools, source extraction for §4.2's URL cross-validation, and `pause_turn`
continuation.
"""

from __future__ import annotations

from typing import Any

import anthropic

from ..config import Settings, get_settings

# Server-side tools. Do NOT also declare code_execution alongside these — the
# _20260209 variants run code internally for dynamic filtering, and a second
# execution environment confuses the model (§1.1).
def web_tools(max_uses: int = 8) -> list[dict[str, Any]]:
    return [
        {"type": "web_search_20260209", "name": "web_search", "max_uses": max_uses},
        {
            "type": "web_fetch_20260209",
            "name": "web_fetch",
            "citations": {"enabled": True},
        },
    ]


# The server-side tool loop caps at 10 iterations and then returns pause_turn.
# Resume by re-sending with the assistant turn appended — never add a
# "Continue." user message (§4.1).
MAX_CONTINUATIONS = 5


# Context editing clears old tool results from the transcript. Safe here because
# the canvas is the durable state (§9.3) — once a row is persisted, the search
# result that produced it is no longer needed in context.
CONTEXT_EDIT_BETA = "context-management-2025-06-27"
CLEAR_TOOL_USES = {"edits": [{"type": "clear_tool_uses_20250919"}]}


class NoCredentials(RuntimeError):
    pass


def get_client(settings: Settings | None = None) -> anthropic.Anthropic:
    settings = settings or get_settings()
    if not settings.anthropic_api_key:
        raise NoCredentials("ANTHROPIC_API_KEY is not set")
    # The SDK already retries 408/409/429/5xx and connection errors with
    # backoff, so no retry loop is hand-rolled on top of it.
    return anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=3)


def describe_error(exc: BaseException) -> tuple[str, bool]:
    """A user-facing message plus whether retrying could plausibly help.

    Marking everything retryable is worse than useless: it invites the user to
    re-run a request that will fail identically, at full cost.
    """
    if isinstance(exc, NoCredentials):
        return "ANTHROPIC_API_KEY is not set on the server.", False
    if isinstance(exc, anthropic.AuthenticationError):
        return "The server's Anthropic API key was rejected.", False
    if isinstance(exc, anthropic.PermissionDeniedError):
        return "The API key is not permitted to use this model.", False
    if isinstance(exc, anthropic.NotFoundError):
        return "The configured model does not exist.", False
    if isinstance(exc, anthropic.BadRequestError):
        # A malformed request fails the same way every time.
        return f"The request was rejected: {exc}", False
    if isinstance(exc, anthropic.RateLimitError):
        return "Rate limited by the Anthropic API — try again shortly.", True
    if isinstance(exc, anthropic.APIConnectionError):
        return "Could not reach the Anthropic API.", True
    if isinstance(exc, anthropic.APIStatusError):
        return f"Anthropic API error {exc.status_code}.", exc.status_code >= 500
    return f"{type(exc).__name__}: {exc}", False


def create(
    messages: list[dict[str, Any]],
    *,
    settings: Settings | None = None,
    system: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int = 16000,
    thinking: bool = True,
    context_management: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Any:
    """One Messages call. Adaptive thinking must be set explicitly (§11)."""
    settings = settings or get_settings()
    client = get_client(settings)

    params: dict[str, Any] = {
        "model": settings.anthropic_model,
        "max_tokens": max_tokens,
        "messages": messages,
        "output_config": {"effort": settings.anthropic_effort},
        **kwargs,
    }
    if thinking:
        params["thinking"] = {"type": "adaptive"}
    if system is not None:
        params["system"] = system
    if tools is not None:
        params["tools"] = tools

    if context_management is not None:
        # Context editing is beta, so it needs the beta namespace and header.
        return client.beta.messages.create(
            betas=[CONTEXT_EDIT_BETA],
            context_management=context_management,
            **params,
        )
    return client.messages.create(**params)


def create_with_continuation(
    messages: list[dict[str, Any]],
    *,
    settings: Settings | None = None,
    max_continuations: int = MAX_CONTINUATIONS,
    **kwargs: Any,
) -> list[Any]:
    """Drive a server-tool turn to completion, resuming on `pause_turn`.

    Returns every response in order, so callers can harvest search results from
    all of them rather than only the last.
    """
    convo = list(messages)
    responses: list[Any] = []

    for _ in range(max_continuations + 1):
        response = create(convo, settings=settings, **kwargs)
        responses.append(response)
        if response.stop_reason != "pause_turn":
            return responses
        # Append the paused assistant turn verbatim and re-send; the server
        # picks up where it left off.
        convo = [*convo, {"role": "assistant", "content": response.content}]

    return responses


def search_results(response: Any) -> list[dict[str, Any]]:
    """Every web_search result in one response, or [] if it did not search.

    Server-tool errors do NOT raise — they come back HTTP 200 with an error
    object in place of the result list. On success `.content` is a *list*; on
    error it is an *object*. Branch before iterating (§4.1).
    """
    results: list[dict[str, Any]] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) != "web_search_tool_result":
            continue
        content = getattr(block, "content", None)
        if not isinstance(content, list):
            continue  # an error object, not results
        for item in content:
            url = getattr(item, "url", None)
            if url:
                results.append(
                    {
                        "url": url,
                        "title": getattr(item, "title", "") or "",
                        "page_age": getattr(item, "page_age", None),
                    }
                )
    return results


def search_errors(response: Any) -> list[str]:
    """Error codes from any web_search/web_fetch block that failed."""
    errors: list[str] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) not in {
            "web_search_tool_result",
            "web_fetch_tool_result",
        }:
            continue
        content = getattr(block, "content", None)
        if isinstance(content, list):
            continue
        code = getattr(content, "error_code", None)
        if code:
            errors.append(code)
    return errors


def container_id(response: Any) -> str | None:
    """Container backing the server tools, if this response created one.

    The _20260209 web tools run dynamic filtering through code execution, so a
    response can carry pending container-backed tool uses. Every follow-up
    request in that conversation must pass the container back or the API
    rejects it with "container_id is required".
    """
    container = getattr(response, "container", None)
    return getattr(container, "id", None) if container is not None else None


def message_text(response: Any) -> str:
    return "".join(
        getattr(block, "text", "")
        for block in getattr(response, "content", []) or []
        if getattr(block, "type", None) == "text"
    )


def citations(response: Any) -> list[dict[str, Any]]:
    """Citations attached to text blocks, when web_fetch citations are enabled."""
    found: list[dict[str, Any]] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) != "text":
            continue
        for citation in getattr(block, "citations", None) or []:
            found.append(
                {
                    "cited_text": getattr(citation, "cited_text", "") or "",
                    "title": getattr(citation, "document_title", None)
                    or getattr(citation, "title", "")
                    or "",
                    "url": getattr(citation, "url", None),
                }
            )
    return found
