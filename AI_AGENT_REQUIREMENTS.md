# AI Chart Agent — Requirements

Turn video-vis into an AI-driven tool: a chatbot in the bottom-right corner takes a
**topic** and a **language**, researches the data with verified sources, normalises it
into a single comparable dataset, and emits a `ChartConfig` the existing renderer can
animate — title, subtitle, and timed captions included.

This document is the build plan. Work through it phase by phase; each phase has its own
acceptance criteria and is independently shippable.

---

## 1. Decisions already made

| Decision | Choice | Why |
|---|---|---|
| LLM provider | **Anthropic** | Built-in web search returns source URLs + citations (§1.1) |
| Model | `claude-sonnet-5` | Same `_20260209` web tools as Opus, materially cheaper (§7) |
| Backend | **FastAPI** in `/backend` | Keeps the API key server-side |
| Frontend | Existing Vue app moved to `/frontend` | Done — Phase 0 |
| Language & topic | Plain strings for now | No enum/taxonomy yet |
| Agent working surface | **Shared data canvas** (§4.0) | Lets the agent iterate instead of one-shotting |

### 1.1 Why the provider must have built-in search

The requirement that decides this isn't brand — it's that **the provider must return the
source URLs**, because §4.2 validates every recorded number against URLs that were
actually retrieved. Anthropic qualifies natively:

- `web_search_20260209` — runs server-side, returns a real result list with URLs and
  titles, and supports *dynamic filtering* (Claude filters results in code before they
  consume context).
- `web_fetch_20260209` — pulls full page content for URLs already in the conversation,
  with `citations: {enabled: true}` attaching verbatim `cited_text` to claims.

> ⚠️ **Do not also declare `code_execution` in `tools`.** The `_20260209` variants run
> code under the hood; a second execution environment confuses the model.

### 1.2 Provider history (why this doc mentions others)

Qwen via Alibaba Cloud Model Studio was evaluated and abandoned. Recorded so it isn't
re-litigated:

- Its search sources are returned **only** on the DashScope-native API — *"the
  OpenAI-compatible protocol does not support returning search sources in the response"*
  — so the obvious `openai`-SDK route would have silently broken verification.
- The account never cleared entitlement: every model on both the native `/api/v1` and the
  Anthropic-compatible `/apps/anthropic` surface returned `AccessDenied.Unpurchased`,
  while the CN region returned `InvalidApiKey`. Account-level, not model-level.
- It also had no strict-schema mode and no general URL fetcher.

If cost ever forces a revisit, the canvas design (§9.3) is what keeps the switch cheap —
verification depends on knowing which URLs were retrieved, not on any vendor's citation
format.

---

## 2. Target repo layout

```
video-vis/
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   └── AssistantWidget.vue      # NEW — the chatbot popover
│   │   ├── lib/agentClient.ts           # NEW — SSE client
│   │   └── types.ts
│   └── vite.config.ts        # proxies /api → backend
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI app + CORS
│   │   ├── routes/chart.py   # SSE endpoint
│   │   ├── llm/
│   │   │   └── anthropic_client.py      # web tools, sources, pause_turn
│   │   ├── canvas/
│   │   │   ├── store.py      # the CSV canvas: load/append/revise/persist
│   │   │   ├── derive.py     # period parsing, unit conversion, conflict flags
│   │   │   └── tools.py      # canvas_* tool definitions + dispatch
│   │   ├── pipeline/
│   │   │   ├── research.py   # Stage 1 agentic loop
│   │   │   └── compose.py    # Stage 3
│   │   ├── schemas.py        # Pydantic models mirroring types.ts
│   │   └── prompts/          # system prompts, one file each
│   ├── .runs/{run_id}/canvas.csv        # per-run canvas (gitignored)
│   ├── pyproject.toml        # uv-managed
│   └── .env.example          # ANTHROPIC_API_KEY=
└── AI_AGENT_REQUIREMENTS.md
```

Python 3.12.10 and uv 0.11.21 are installed. On this machine uv needs
`UV_CACHE_DIR=/d/workspace/.uv-cache` — see `backend/README.md`.

---

## 3. Architecture

```
Browser (Vue)              FastAPI                        Anthropic API
─────────────              ───────                        ─────────────
AssistantWidget
 topic + language ─POST /api/chart/generate─►
                        ┌──────────────────────────┐
                        │  DATA CANVAS (per run)   │
                        │  .runs/{id}/canvas.csv   │◄──┐
                        └──────────────────────────┘   │
                                                       │
                        Stage 1 research LOOP ─────────┼──► messages.create
                          agent searches ──────────────┘     + web_search
                          agent appends rows                 + web_fetch
                          python derives columns             + canvas_* tools
                          agent reads gap report             (all in ONE call)
                          agent searches again ↺
                 ◄─SSE: stage / token / sources / canvas─
                        Stage 3 compose ──► messages.create
                                              + strict tool (reads canvas)
                 ◄─SSE: config / done────────
 onApply(config) → existing AnimatedChart renders
```

**The API key never leaves the backend.** The browser only ever talks to FastAPI.

---

## 4. The pipeline

### 4.0 The data canvas

A per-run tabular working surface the agent fills incrementally and revises. It is the
**shared state between every stage**, persisted at `backend/.runs/{run_id}/canvas.csv` so
it survives across steps, can be downloaded for inspection, and makes a failed run
debuggable.

| Column | Written by | Notes |
|---|---|---|
| `row_id` | Python | Stable handle for revisions |
| `series` | Agent | e.g. `OpenAI` |
| `period_label` | Agent | **Verbatim from the source** — `FY2024`, `Q3 2025` |
| `raw_value` | Agent | The number exactly as stated |
| `raw_unit` | Agent | Enum: `USD`, `USD_thousands`, `USD_millions`, `USD_billions`, `count`, `percent` |
| `source_url` | Agent | Must match a URL actually retrieved this run — §4.2 |
| `source_title` | Agent | |
| `cited_text` | Agent | Verbatim snippet supporting the number |
| `published_at` | Agent | Drives conflict resolution (§9.2) |
| `period_iso` | **Python** | Parsed from `period_label` → the renderer's `time` |
| `value_normalized` | **Python** | Converted to the run's target unit |
| `status` | **Python** | `ok` / `conflict` / `unverified_url` / `unparseable_period` |

**Raw and derived columns are strictly separated.** The agent only ever writes what a
source literally says; Python computes everything derived. The model never does the
arithmetic, but it still *sees* and iterates on the normalised result.

#### Canvas tools

Custom (client-side) tools, executed by FastAPI against the run's table:

| Tool | Purpose |
|---|---|
| `canvas_set_target(series[], start, end)` | Declare what the run is collecting. Called once, early — see §4.3. |
| `canvas_append_rows(rows[])` | Add observations. Returns per-row accept/reject + reason. |
| `canvas_read(series?, status?)` | Return the table **plus a gap report** (§4.3). |
| `canvas_revise_row(row_id, ...)` | Correct a row after a better source turns up. |
| `canvas_drop_row(row_id, reason)` | Remove a row that proved wrong. Never silent. |

> ⚠️ **Typed tools, not raw CSV text editing.** Editing the CSV as text needs exact string
> matches and breaks on quoting, embedded commas, and near-duplicate rows. A typed append
> API gets schema validation for free — and lets us make `source_url` a **required**
> field, so the agent *structurally cannot* record a number without a citation. The file
> is still written as real CSV for download and debugging.

### 4.1 Stage 1 — Research loop over the canvas

Anthropic allows **server tools and custom tools in the same request**, so this is one
ordinary agentic loop — the model searches and records in a single conversation:

```python
tools = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 12},
    {"type": "web_fetch_20260209", "name": "web_fetch", "citations": {"enabled": True}},
    *CANVAS_TOOLS,
]
```

The loop the agent is prompted to run:

1. `canvas_read` → see what exists
2. `canvas_set_target` → declare the series and period range the topic needs
3. Search / fetch for a specific gap
4. `canvas_append_rows` with what the article actually states
5. Repeat from 3 until the gap report is empty or the remainder is unavailable

**Implementation notes:**

- **Write a manual loop, not the SDK tool runner.** The runner does not auto-resume
  `pause_turn`, and in Python it cannot be resumed mid-loop — a paused turn silently ends
  the run and returns a truncated result. With server tools in the mix `pause_turn` is
  routine (the server-side loop caps at 10 iterations). Handle it explicitly: append
  `response.content` as an assistant turn and re-send, no "Continue." message, cap ~5.
  `llm/anthropic_client.create_with_continuation` already does this.
- Return **all** `tool_result` blocks for one assistant turn in a **single** user message.
  Splitting them trains the model out of parallel tool calls.
- **Server-tool errors do not raise.** HTTP 200 with an error object inside
  `web_search_tool_result`. On success `.content` is a **list**; on error it is an
  **object** (`{"error_code": "max_uses_exceeded"}`). Branch before iterating —
  `search_results()` / `search_errors()` handle this.
- Bound the loop: max iterations, `max_uses` on search, and a token budget. A vague topic
  can otherwise loop indefinitely chasing gaps that don't exist.
- **Carry the server-tool `container` forward.** The `_20260209` tools run dynamic
  filtering through code execution, so once a response opens a container every later
  request must pass it back. Dropping it is a hard 400 — *"container_id is required when
  there are pending tool uses generated by code execution with tools"* — and no amount of
  mocked testing surfaces it.
- **`max_uses` is per request, not per conversation.** It resets each turn. A turn that
  exhausts it emits `max_uses_exceeded` notices and the model recovers on the next turn,
  costing one wasted round trip.
- **Turns are long.** Measured: 101s for a turn containing 26 server tool uses, 20 search
  results and 6 code-execution blocks. Budget minutes, not seconds, and stream so the UI
  is not silent.

### 4.2 URL cross-validation — the anti-fabrication guard

The agent *types* `source_url` into a tool call, so it could invent one. The canvas rejects
that:

> **Every URL from a `web_search_tool_result` goes into a per-run allowed set.
> `canvas_append_rows` rejects any row whose `source_url` is not in that set, and returns
> the reason to the agent.**

This makes "verified sources" a structural property rather than a hope, for the cost of a
set lookup. Rejected rows go back to the agent so it can retry with a real source. Keep
`citations` enabled on `web_fetch` regardless — API-emitted `cited_text` is stronger
evidence than anything the model retypes.

### 4.3 The gap report

What makes the loop converge — and it only works if it knows what "done" means.

**Without a declared target it can only compare recorded data against itself**, so a
series the agent never adds is never reported missing and the loop concludes it has
finished while most of the request is unmet. `canvas_set_target` fixes that: gaps are
measured against the series and range that were actually asked for, and a series with no
rows at all comes back flagged `has_no_data`.

Two things this deliberately does *not* do:

- It is a **research-time** signal, not a finalisation rule. A period still missing at the
  end is not an error — §9.1 still governs, and nothing is ever back-filled.
- Series discovered along the way that were not in the target are still reported (marked
  `off_target`), using their own coverage rather than the target range.

On every `canvas_read`, Python computes:

- The union period range across all series (per §9.1)
- Per series, which periods within its own coverage are missing
- Rows flagged `conflict` — two sources, same `series` + `period`, different values
- Rows flagged `unverified_url` or `unparseable_period`

The agent works this list. It's also where §9.2 is enforced: surface the conflict, let the
agent resolve it with `canvas_revise_row`, and record the reason.

### 4.4 Stage 2 — Normalisation (Python, continuous)

Not a discrete phase — normalisation runs **on every canvas write**, so the agent always
reads an up-to-date, normalised table.

1. Parse `period_label` → `period_iso`; flag `unparseable_period` rather than guessing.
2. Convert `raw_value` + `raw_unit` → `value_normalized` in one target unit; record the
   unit for `yLabel`.
3. Detect conflicts on `(series, period)`; resolve by newest `published_at` (§9.2).
4. On finalisation: sort by time, **use the union of all series ranges** (§9.1), never
   interpolate before a series' first real datapoint, assign `DEFAULT_COLORS`, and emit
   `Series[]` matching `frontend/src/types.ts` exactly.

### 4.5 Stage 3 — Compose the chart (tool call)

A separate call that reads the finalised canvas and produces presentation: title,
subtitle, axis labels, and **captions with timestamps**.

> ⚠️ **This must be a separate call from Stage 1.** `output_config.format` (structured
> outputs) **returns a 400 when citations are enabled**. Stage 1 needs citations; Stage 3
> needs a guaranteed schema. They cannot be the same request.

Use a **strict tool** so the arguments validate exactly:

```python
BUILD_CHART_TOOL = {
    "name": "build_chart",
    "description": (
        "Produce the final chart presentation. Call exactly once. "
        "Captions must be spaced across the animation and must not overlap."
    ),
    "strict": True,                     # top-level, NOT on tool_choice
    "input_schema": {
        "type": "object",
        "properties": {
            "title":     {"type": "string"},
            "subtitle":  {"type": "string"},
            "xLabel":    {"type": "string"},
            "yLabel":    {"type": "string"},
            "currency":  {"type": "string"},
            "currencyPosition": {"type": "string", "enum": ["prefix", "suffix"]},
            "captions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text":     {"type": "string"},
                        "appearAt": {"type": "number", "description": "seconds from start"},
                        "duration": {"type": "number", "description": "seconds visible"},
                    },
                    "required": ["text", "appearAt", "duration"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["title", "subtitle", "xLabel", "yLabel",
                     "currency", "currencyPosition", "captions"],
        "additionalProperties": False,
    },
}
```

`strict: true` requires `additionalProperties: false` and `required` on every object.

**Caption timing needs guarding.** The model can only place `appearAt` sensibly if we tell
it `animationDuration` and the per-series time range. Put both in the user turn, then
**validate server-side** — clamp `appearAt` to `[0, animationDuration]`, drop overlaps,
cap the count. Never trust model timestamps straight into the renderer.

Captions are where the canvas pays off twice: the agent can reference a specific
`(series, period)` row, so *"Anthropic enters in 2021"* is anchored to a real datapoint
with a real source.

All other `ChartConfig` fields (`aspectRatio`, `iconSize`, `chartFont`, `textSize`,
`showEndRanking`, `numberSuffixes`, `allowNegative`) are filled server-side from defaults
and the request — the model does not choose them.

**Language** governs title, subtitle, labels, and captions. Pair it with `numberSuffixes`
— Indonesian output should use the `Indonesian` preset (`Rb`/`Jt`/`M`), not `K`/`M`/`B`.

---

## 5. HTTP contract

### `POST /api/chart/generate` → `text/event-stream`

```jsonc
// request
{ "topic": "OpenAI vs Anthropic revenue", "language": "English",
  "aspectRatio": "9:16", "animationDuration": 8 }
```

| SSE event | Payload | Meaning |
|---|---|---|
| `stage`   | `{"name": "research"\|"compose", "status": "start"\|"done"}` | Drives the progress UI |
| `token`   | `{"text": "..."}` | Streamed assistant prose |
| `canvas`  | `{"rows": n, "series": [...], "gaps": [...]}` | Live table state |
| `sources` | `{"sources": [{"series","time","title","url","cited_text"}]}` | Per-datapoint citation list |
| `config`  | `{"config": { ...ChartConfig }}` | Ready to hand to `onApply` |
| `error`   | `{"message": "...", "retryable": bool}` | Show inline in the widget |
| `done`    | `{}` | Close the stream |

Stream from the start — a research loop takes a while and a silent spinner reads as a hang.

### `GET /api/runs/{run_id}/canvas.csv` → the raw canvas

For download and debugging. Makes a bad run diagnosable after the fact.

### `GET /api/health` → `{"ok": true}`

---

## 6. Frontend widget

`AssistantWidget.vue` — floating action button bottom-right, opens a popover panel.

- Collapsed: circular button, `position: fixed; bottom: 24px; right: 24px`.
- Expanded: ~380×520 panel, same dark tokens as `style.css` (`--surface`, `--border`).
- Contents: topic input, language input, Generate button, streaming transcript, a live
  **canvas summary** (rows found / gaps remaining), a collapsible **Sources** list with
  real links, and an **Apply to chart** button.
- `Apply` emits the `ChartConfig` upward; `App.vue` routes it into the existing
  `onApply(c)` — the renderer needs no changes.
- Must not collide with the chart preview or the platform-overlay controls.

---

## 7. Cost, caching, and limits

| Model | Input | Output | Notes |
|---|---|---|---|
| **`claude-sonnet-5`** (default) | $3 /MTok | $15 /MTok | **Intro $2/$10 through 2026-08-31** |
| `claude-opus-4-8` | $5 /MTok | $25 /MTok | Swap via `ANTHROPIC_MODEL` if quality demands it |
| `claude-haiku-4-5` | $1 /MTok | $5 /MTok | ⚠️ only the older `web_search_20250305`; 200K context |

- The research **loop** is the cost driver: every iteration resends the conversation and
  search results are large.
- **Cache the system prompt + tool definitions** (`cache_control: {"type": "ephemeral"}`).
  Cache reads cost ~0.1×. Minimum cacheable prefix is **2048 tokens** on Sonnet 5 (4096 on
  Opus 4.8) — below that it silently won't cache (`cache_creation_input_tokens: 0`).
- Render order is `tools` → `system` → `messages`. Keep the `canvas_*` tool schemas
  **byte-stable** — they render at position 0, so any change invalidates the whole cache.
  Build them as module constants, never per-run.
- Verify with `usage.cache_read_input_tokens`. Zero across repeated runs means a silent
  invalidator.
- Consider **context editing** (`clear_tool_uses_20250919`) for long loops — old search
  results can be cleared once their rows are in the canvas, since the canvas *is* the
  durable state. This is the main lever on loop cost.
- Cap `max_uses` on web search plus a per-run token budget so a bad topic can't run up a
  bill.

---

## 8. Phases

### Phase 0 — Restructure ✅ **done** (`410855f`)
- [x] Frontend moved to `/frontend`, launch config updated, build + render verified

### Phase 1 — Backend skeleton ✅ **code done** (`1b0ab41`, + Anthropic swap)
- [x] `uv` project, FastAPI app, CORS, `/api/health`
- [x] Vite proxy `/api` → `:8000`, verified end-to-end through the proxy
- [x] `.env` / `.runs/` gitignored
- [ ] **Smoke test passes** — needs `ANTHROPIC_API_KEY` in `backend/.env`, then
      `uv run python scripts/smoke_anthropic.py`

### Phase 2 — The canvas ✅ **done** — 63 tests, no model involved
- [x] `store.py` — append / revise / drop / persist to CSV
- [x] `derive.py` — period parsing, unit conversion, conflict detection
- [x] Gap report computation (late-starting series per §9.1)
- [x] URL cross-validation against a retrieved-URL set
- [x] `schemas.py` — Pydantic mirrors of types.ts, camelCase on the wire
- [x] Tests: mixed units, unparseable period, conflicting sources, fabricated URL

### Phase 3 — Stage 1 research loop ✅ **done** — verified on a live run
- [x] `canvas_*` tool definitions + dispatch (module constants, cache-stable)
- [x] Manual agentic loop with `pause_turn` handling (cap 5)
- [x] Server-tool container carried across turns (§4.1)
- [x] Server-tool error branch (list vs object)
- [x] Loop bounds: iterations, `max_uses`, tokens
- [x] SSE `token` / `canvas` / `sources` / `notice` events + `/api/chart/generate`

Live result on "OpenAI vs Anthropic annual revenue, 2023 to 2025": 6 rows, both
series, 2023–2025 complete, **5 distinct sources**, `cited_text` and
`published_at` on every row, mixed units (`USD_millions` + `USD_billions`)
normalised correctly, zero fabricated URLs.

### Phase 4 — Stage 3 compose ✅ acceptance: valid ChartConfig, captions in range
- [ ] `build_chart` strict tool
- [ ] Server-side caption clamping + overlap rejection
- [ ] Language-aware `numberSuffixes` selection
- [ ] Finalisation: canvas → `Series[]`

### Phase 5 — Widget ✅ acceptance: end-to-end topic → animated chart
- [ ] `AssistantWidget.vue` + SSE client
- [ ] Live canvas summary + sources list
- [ ] Wire `Apply` into `onApply`
- [ ] Error and empty states

### Phase 6 — Hardening
- [ ] Per-run token budget + timeout
- [ ] Context editing once rows are persisted
- [ ] Typed error handling (`RateLimitError` → retryable, `APIStatusError` → not)
- [ ] Prompt caching verified via `cache_read_input_tokens`

---

## 9. Decisions

### 9.1 Gap policy — union of ranges, late series start late ✅

If OpenAI has 2020–2025 and Anthropic 2021–2025, the chart **starts at 2020 with
Anthropic absent** and Anthropic's line begins when its data does.

Verified against the renderer — this needs no renderer changes:

- `getVisibleData` returns zero points for a series whose first datapoint is later than
  the current time (`sorted[0].time > currentTime`), so nothing is drawn for it.
- The endpoint loop skips series with no visible points (`vd.points.length < 1`).
- **The legend still lists the absent series.** `getRankedLegendItems` assigns it
  `Number.NEGATIVE_INFINITY`, so it sorts to the bottom but is still drawn — at 2020,
  Anthropic appears as a name + colour swatch with no line. This reads as intentional
  (both contenders established up front); flagged so it isn't mistaken for a bug.

Normalisation must **not** back-fill zeros to make ranges match. A zero is a factual claim
that the value was zero; absence is the honest representation and the renderer handles it.

### 9.2 Source trust — accept anything the search returns ✅

No domain allowlist. Verification comes from the source being **shown**, not from a
gatekeeper — the user sees it and judges it.

Consequences, all handled by the canvas:

- A series is **multi-source by default** — 2024 from an earnings report, 2025 from a
  later article. Provenance is therefore **per row**, not per series.
- Two sources can disagree about the same `(series, period)`. Rule: prefer the more recent
  `published_at`, flag the row `conflict`, and surface it rather than silently picking.
- Because the model types `source_url`, it is cross-validated against actually-retrieved
  URLs (§4.2).

> ⚠️ `DataPoint` in `frontend/src/types.ts` is `{time, label, value}` — there is **no**
> source field, and adding one changes the shape the renderer consumes. Provenance lives
> in the canvas and travels over the `sources` SSE event; the renderer still receives an
> unchanged `ChartConfig`.

### 9.3 Canvas is the source of truth ✅

Once a row is in the canvas it's durable state; the conversation transcript is disposable.
This is what allows context editing on long loops, resuming a failed run, downloading the
evidence behind any chart — and what would make a future provider switch cheap.

---

## 10. Open questions

1. **Failure mode** — if research finds no usable numbers, fail loudly or return a
   partial chart? Recommend failing loudly.
2. **Series icons** — `Series.image` (the endpoint logo) has no automatic source. Leave
   empty, or attempt favicon lookup from the cited domain?
3. **Rate limits** — single-user local, or deployed and shared?
4. **Canvas reuse across runs** — should a new topic start empty, or can a user re-open a
   previous run's canvas and extend it? Affects whether `run_id` is user-visible.

---

## 11. Reference — API shapes worth not re-deriving

| Thing | Correct form |
|---|---|
| Model id | `claude-sonnet-5` / `claude-opus-4-8` (no date suffix) |
| Thinking | `thinking={"type": "adaptive"}` — `budget_tokens` is a **400** |
| Effort | `output_config={"effort": "high"}` — inside `output_config`, not top-level |
| Sampling | `temperature`/`top_p`/`top_k` are **removed** — sending them is a 400 |
| Web search | `{"type": "web_search_20260209", "name": "web_search"}` |
| Web fetch | `{"type": "web_fetch_20260209", "name": "web_fetch"}` — only fetches URLs already in the conversation |
| Never pair with | `code_execution` — the `_20260209` tools already run code |
| Strict tool | `"strict": True` top-level on the tool def |
| Structured output | `output_config={"format": {...}}` — **incompatible with citations** |
| Parallel tools | Return every `tool_result` for one turn in a **single** user message |
| `pause_turn` | Append `response.content`, re-send, no "Continue." message |
| Server-tool errors | HTTP 200; `.content` is a list on success, an **object** on error |
| Streaming | `client.messages.stream(...)` → `.get_final_message()`; required above ~16K `max_tokens` |
| Prefill | Last-assistant-turn prefill is a **400** — use structured outputs instead |
| Context editing | `context_management={"edits": [{"type": "clear_tool_uses_20250919"}]}`, beta `context-management-2025-06-27` |
| Errors | `anthropic.RateLimitError` (retry) → `anthropic.APIStatusError` → `anthropic.APIConnectionError` |
