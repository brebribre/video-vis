"""Phase 1 smoke test (§8).

One native DashScope call with `enable_search` + `enable_source`, asserting that
`search_info.search_results` comes back populated. This confirms three things
before any pipeline is built on top of them: the API key works, the configured
region serves the configured model, and search sources are actually returned.

    cd backend && uv run python scripts/smoke_dashscope.py

Exit code 0 = usable. Anything else = fix the config before continuing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.llm.dashscope_client import (  # noqa: E402
    DashScopeError,
    generate,
    message_text,
    search_results,
)

PROMPT = "What was OpenAI's annualised revenue in 2024? Cite your sources."


def main() -> int:
    settings = get_settings()
    print(f"region : {settings.dashscope_region} ({settings.base_url})")
    print(f"model  : {settings.dashscope_model}")

    if not settings.dashscope_api_key:
        print("\nFAIL: DASHSCOPE_API_KEY is not set. Copy .env.example to .env first.")
        return 2

    try:
        response = generate(
            [{"role": "user", "content": PROMPT}],
            settings=settings,
            enable_search=True,
        )
    except DashScopeError as exc:
        print(f"\nFAIL: {exc}")
        if exc.code in {"InvalidApiKey", "Arrearage"}:
            print("  → check DASHSCOPE_API_KEY and the account's billing state")
        if exc.code in {"InvalidParameter", "ModelNotFound", "model_not_found"}:
            print(f"  → {settings.dashscope_model} may not exist in this region (§1.2)")
        return 1

    results = search_results(response)
    text = message_text(response)

    print(f"\nsources: {len(results)}")
    for result in results[:5]:
        print(f"  [{result.get('index')}] {result.get('title')}\n      {result.get('url')}")
    print(f"\ntext ({len(text)} chars):\n{text[:600]}")

    if not results:
        print(
            "\nFAIL: search_info.search_results is empty. Without it §4.2's URL "
            "cross-validation cannot work — check that the native API (not the "
            "OpenAI-compatible endpoint) is in use and that enable_source is set."
        )
        return 1

    citation_markers = any(f"[{r.get('index')}]" in text for r in results)
    print(f"\ncitation markers present: {citation_markers}")
    print("PASS: native search returns sources; region and model are usable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
