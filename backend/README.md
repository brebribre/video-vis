# video-vis backend

FastAPI service behind the AI chart agent. It holds the Anthropic API key so the
browser never sees it — see `../AI_AGENT_REQUIREMENTS.md` for the full design.

## Setup

```bash
cd backend
uv sync                      # creates .venv from pyproject/uv.lock
cp .env.example .env         # then fill in ANTHROPIC_API_KEY
```

> **Windows, project on `D:`** — `uv` puts its cache on `C:` by default and
> cannot move temp files across drives, which fails with a confusing
> "Failed to inspect Python interpreter" error. Export a cache dir on the same
> drive first: `export UV_CACHE_DIR=/d/workspace/.uv-cache`.

## Run

```bash
uv run uvicorn app.main:app --reload --port 8000
```

`GET http://localhost:8000/api/health` → `{"ok": true}`.

The Vite dev server proxies `/api` here, so the frontend calls same-origin paths
(`fetch('/api/...')`) in development.

## Smoke test the model

Before building on top of the API, confirm the key and model together:

```bash
uv run python scripts/smoke_anthropic.py
```

It makes one Messages call with the server-side web tools and fails loudly if no
search results come back — without source URLs the §4.2 URL cross-validation has
nothing to check numbers against. It also handles `pause_turn` continuation, so
it exercises the same path the research loop will.

## Layout

| Path | Purpose |
|---|---|
| `app/main.py` | App factory, CORS, router wiring |
| `app/config.py` | Env-backed settings; the only place the API key is read |
| `app/routes/` | HTTP surface (`health` now, `chart` SSE in Phase 3) |
| `app/llm/` | Anthropic Messages wrapper: web tools, source extraction, `pause_turn` |
| `app/canvas/` | Per-run data canvas (Phase 2) |
| `app/pipeline/` | Research loop and compose stage (Phases 3–4) |
| `.runs/{run_id}/` | Per-run canvas CSV — gitignored |
