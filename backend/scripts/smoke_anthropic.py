"""Phase 1 smoke test (§8).

One Messages call with the server-side web tools, asserting that real search
results come back. This confirms three things before any pipeline is built on
them: the API key works, the configured model serves the _20260209 tools, and
source URLs are actually returned — §4.2's URL cross-validation has nothing to
check numbers against without them.

    cd backend && uv run python scripts/smoke_anthropic.py

Exit code 0 = usable. Anything else = fix the config before continuing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.llm.anthropic_client import (  # noqa: E402
    NoCredentials,
    citations,
    create_with_continuation,
    message_text,
    search_errors,
    search_results,
    web_tools,
)

PROMPT = "What was OpenAI's annualised revenue in 2024? Cite your sources."


def main() -> int:
    settings = get_settings()
    print(f"model  : {settings.anthropic_model}")
    print(f"effort : {settings.anthropic_effort}")

    if not settings.supports_modern_search:
        print(
            f"\nFAIL: {settings.anthropic_model} does not support the "
            "web_search_20260209 tools. Pick a model from MODELS_WITH_MODERN_SEARCH."
        )
        return 2

    try:
        responses = create_with_continuation(
            [{"role": "user", "content": PROMPT}],
            settings=settings,
            tools=web_tools(max_uses=4),
        )
    except NoCredentials:
        print("\nFAIL: ANTHROPIC_API_KEY is not set. Copy .env.example to .env first.")
        return 2
    except anthropic.NotFoundError:
        print(f"\nFAIL: model {settings.anthropic_model!r} not found.")
        return 1
    except anthropic.AuthenticationError:
        print("\nFAIL: ANTHROPIC_API_KEY was rejected.")
        return 1
    except anthropic.RateLimitError:
        print("\nFAIL: rate limited — retryable, try again shortly.")
        return 1
    except anthropic.APIStatusError as exc:
        print(f"\nFAIL: API error {exc.status_code}: {exc.message}")
        return 1
    except anthropic.APIConnectionError as exc:
        print(f"\nFAIL: could not reach the API: {exc}")
        return 1

    results = [r for resp in responses for r in search_results(resp)]
    errors = [e for resp in responses for e in search_errors(resp)]
    cites = [c for resp in responses for c in citations(resp)]
    text = message_text(responses[-1])

    print(f"\nturns  : {len(responses)} (pause_turn continuations handled)")
    print(f"sources: {len(results)}")
    for result in results[:5]:
        print(f"  - {result['title']}\n    {result['url']}")
    if errors:
        print(f"\nserver-tool errors: {errors}")
    print(f"\ncitations: {len(cites)}")
    for cite in cites[:3]:
        print(f"  - {cite['title']}: {cite['cited_text'][:110]}")
    print(f"\ntext ({len(text)} chars):\n{text[:600]}")

    if not results:
        print(
            "\nFAIL: no web_search results came back. Without source URLs the "
            "§4.2 URL cross-validation cannot work."
        )
        return 1

    print("\nPASS: web search returns sources; model and key are usable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
