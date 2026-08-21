# video-vis backend

FastAPI service behind the AI chart agent. It holds the DashScope API key so the
browser never sees it — see `../AI_AGENT_REQUIREMENTS.md` for the full design.

## Setup

```bash
cd backend
uv sync                      # creates .venv from pyproject/uv.lock
cp .env.example .env         # then fill in DASHSCOPE_API_KEY
```

## Run

```bash
uv run uvicorn app.main:app --reload --port 8000
```

`GET http://localhost:8000/api/health` → `{"ok": true}`.

The Vite dev server proxies `/api` here, so the frontend calls same-origin paths
(`fetch('/api/...')`) in development.

## Smoke test the model

Before building on top of DashScope, confirm the key, region and model together:

```bash
uv run python scripts/smoke_dashscope.py
```

It makes one native call with `enable_search` + `enable_source` and fails loudly
if `search_info.search_results` comes back empty — without that list the §4.2
URL cross-validation has nothing to check numbers against.

## Layout

| Path | Purpose |
|---|---|
| `app/main.py` | App factory, CORS, router wiring |
| `app/config.py` | Env-backed settings; the only place the API key is read |
| `app/routes/` | HTTP surface (`health` now, `chart` SSE in Phase 3) |
| `app/llm/` | Native DashScope wrapper |
| `app/canvas/` | Per-run data canvas (Phase 2) |
| `app/pipeline/` | Research loop and compose stage (Phases 3–4) |
| `.runs/{run_id}/` | Per-run canvas CSV — gitignored |
