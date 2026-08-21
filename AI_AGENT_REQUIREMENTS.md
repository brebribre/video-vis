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
| LLM provider | **Qwen — Alibaba Cloud Model Studio** | Chosen; ~15× cheaper than Opus with built-in search |
| API surface | **DashScope native** — *not* OpenAI-compatible | Forced by §1.2 |
| Model | `qwen3.7-plus` (verify availability per region) | 1M context, 131K max output, ~$0.32/$1.28 per MTok |
| Backend | **FastAPI** in `/backend` | Keeps the API key server-side |
| Frontend | Existing Vue app moved to `/frontend` | — |
| Language & topic | Plain strings for now | No enum/taxonomy yet |
| Agent working surface | **Shared data canvas** (§4.0) | Lets the agent iterate instead of one-shotting |

### 1.1 Why a built-in-search provider at all

The original question was whether to use a specialised agent from another provider for web
research. The answer that matters isn't brand — it's that **the provider must return the
source URLs**, because §4.2 validates every recorded number against URLs that were
actually retrieved. Qwen qualifies: `enable_search` plus `search_options.enable_source`
returns a real result list, and `enable_citation` inserts `[1]`-style markers tying claims
to it.

### 1.2 ⚠️ Must use the DashScope native API

Three Qwen API surfaces exist and **they are not interchangeable for our purposes**:

| Surface | `enable_search` | Returns sources? | Citation markers? |
|---|---|---|---|
| **DashScope native** | ✅ | ✅ `search_info.search_results` | ✅ `enable_citation` |
| Responses API | ✅ via `tools: [{"type":"web_search"}]` | ✅ `action.sources` | ❌ |
| OpenAI-compatible | ✅ via `extra_body` | ❌ **not returned** | ❌ |

> The docs state plainly: *"The OpenAI-compatible protocol does not support returning
> search sources in the response."*

So the obvious move — point the `openai` Python SDK at the compatible endpoint — **breaks
the entire verification design**. Use the `dashscope` SDK (or raw HTTP to the DashScope
endpoint). Budget for this: it means no drop-in provider portability later.

Region also matters: `dashscope-intl.aliyuncs.com` (international) vs
`dashscope.aliyuncs.com` (China mainland). **Model availability differs by region** — the
published model list is region-scoped, so confirm `qwen3.7-plus` in the target region
before pinning it.

### 1.3 What we give up versus Anthropic

Recorded honestly so nobody rediscovers these mid-build:

1. **No strict-schema guarantee.** There is no `strict: true`. Only
   `response_format: {"type": "json_object"}`, and the docs require *the prompt itself* to
   instruct JSON output. Stage 3 therefore needs a **validate-and-retry loop** (§4.5).
2. **No general URL fetcher.** There's no direct equivalent of fetching an arbitrary URL
   already in the conversation. We get search results and snippets; full article text
   needs our own fetcher, or the Responses API's `web_extractor` (unverified — check
   before relying on it).
3. **Search-plus-tools in one request is unconfirmed.** The docs neither permit nor forbid
   combining `enable_search` with `tools`. §4.1 is designed so this doesn't matter.

---

## 2. Target repo layout

```
video-vis/
├── frontend/                 # ← everything currently at root
│   ├── src/
│   │   ├── components/
│   │   │   └── AssistantWidget.vue      # NEW — the chatbot popover
│   │   ├── lib/agentClient.ts           # NEW — SSE client
│   │   └── types.ts
│   ├── index.html
│   ├── package.json
│   └── vite.config.ts        # + proxy /api → backend
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI app + CORS
│   │   ├── routes/chart.py   # SSE endpoint
│   │   ├── llm/
│   │   │   ├── dashscope_client.py      # native DashScope wrapper
│   │   │   └── retry.py                 # JSON validate-and-retry
│   │   ├── canvas/
│   │   │   ├── store.py      # the CSV canvas: load/append/revise/persist
│   │   │   ├── derive.py     # period parsing, unit conversion, conflict flags
│   │   │   └── tools.py      # canvas_* tool definitions + dispatch
│   │   ├── pipeline/
│   │   │   ├── research.py   # Stage 1 search/extract alternation
│   │   │   └── compose.py    # Stage 3
│   │   ├── schemas.py        # Pydantic models mirroring types.ts
│   │   └── prompts/          # system prompts, one file each
│   ├── .runs/{run_id}/canvas.csv        # per-run canvas (gitignored)
│   ├── pyproject.toml        # uv-managed
│   └── .env.example          # DASHSCOPE_API_KEY=
└── AI_AGENT_REQUIREMENTS.md
```

Python 3.12.10 and uv 0.11.21 are already installed on this machine.

---

## 3. Architecture

```
Browser (Vue)              FastAPI                        Qwen / DashScope
─────────────              ───────                        ────────────────
AssistantWidget
 topic + language ─POST /api/chart/generate─►
                        ┌──────────────────────────┐
                        │  DATA CANVAS (per run)   │
                        │  .runs/{id}/canvas.csv   │◄──┐
                        └──────────────────────────┘   │
                                                       │
                        Stage 1 LOOP                   │
                          a. canvas_read → gap report  │
                          b. SEARCH turn  ─────────────┼─► enable_search
                             (no tools)                │    + enable_source
                             → prose + search_results  │    + enable_citation
                          c. EXTRACT turn ─────────────┼─► tools=[canvas_*]
                             (no search)               │    (no search)
                          d. validate + persist ───────┘
                          ↺ until gaps closed
                 ◄─SSE: stage / token / sources / canvas─
                        Stage 3 compose ──► response_format json_object
                                              + validate-and-retry
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
| `source_url` | Agent | Must match a URL actually returned by search — see §4.2 |
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

Function-calling tools, executed by FastAPI against the run's table:

| Tool | Purpose |
|---|---|
| `canvas_append_rows(rows[])` | Add observations. Returns per-row accept/reject + reason. |
| `canvas_read(series?, status?)` | Return the table **plus a gap report** (§4.3). |
| `canvas_revise_row(row_id, ...)` | Correct a row after a better source turns up. |
| `canvas_drop_row(row_id, reason)` | Remove a row that proved wrong. Never silent. |

> ⚠️ **Typed tools, not raw CSV text editing.** Editing the CSV as text needs exact string
> matches and breaks on quoting, embedded commas, and near-duplicate rows. A typed append
> API gets schema validation for free — and lets us make `source_url` a **required**
> field, so the agent *structurally cannot* record a number without a citation. The file
> is still written as real CSV for download and debugging.

### 4.1 Stage 1 — Search / extract alternation

Because combining `enable_search` with `tools` is unverified (§1.3), the loop **alternates
two single-purpose turns**. This sidesteps the unknown entirely, and turns out to be
better engineering anyway: each turn is small, cheap, and independently cacheable.

Per iteration:

| Step | Who | Request |
|---|---|---|
| a | Python | `canvas_read` → gap report. No model call. |
| b | Model | **SEARCH turn**: `enable_search: true`, `search_options: {enable_source: true, enable_citation: true, forced_search: true, search_strategy: "agent"}`. **No `tools`.** Prompt targets one specific gap. |
| c | Python | Record every URL from `search_info.search_results` into the run's retrieved-URL set. |
| d | Model | **EXTRACT turn**: `tools=[canvas_append_rows]`. **No search.** Input is the search prose + result list. |
| e | Python | Validate rows (§4.2), derive columns (§4.4), persist, emit SSE. |

`search_options` fields, confirmed from the docs:

| Field | Values |
|---|---|
| `search_strategy` | `turbo` (default) / `max` / `agent` / `agent_max` |
| `enable_source` | bool — **required** for us; returns the result list |
| `enable_citation` | bool — inserts markers into the text |
| `citation_format` | `[<number>]` (default) / `[ref_<number>]` |
| `forced_search` | bool — forces a search rather than answering from parameters |
| `enable_search_extension` | bool |

Response shape:

```python
search_info = {
    "search_results": [
        {"index": 1, "title": "...", "url": "...", "site_name": "...", "icon": "..."}
    ],
    "extra_tool_info": [],
}
```

**Set `forced_search: true` on search turns.** Otherwise the model may answer from
parametric memory, producing numbers with no `search_results` behind them — which §4.2
will then reject, wasting the turn.

**Bound the loop:** max iterations, max search turns, and a token budget. A vague topic
can otherwise loop indefinitely chasing gaps that don't exist.

> 🔬 **Spike worth running in Phase 3:** test whether `enable_search` and `tools` are
> accepted in one request. If they are, the two turns can collapse into one agentic loop.
> The alternating design works either way, so this is an optimisation, not a blocker.

### 4.2 URL cross-validation — the anti-fabrication guard

The agent *types* `source_url` into a tool call, so it could invent one. The canvas rejects
that:

> **Every URL from `search_info.search_results` goes into a per-run allowed set.
> `canvas_append_rows` rejects any row whose `source_url` is not in that set, and returns
> the reason to the agent.**

This makes "verified sources" a structural property rather than a hope, for the cost of a
set lookup. Rejected rows go back to the agent so it can retry with a real source.

This guard is also **why the provider swap was affordable** — verification never depended
on Anthropic-style citation blocks, only on knowing which URLs were really retrieved.

### 4.3 The gap report

What makes the loop converge. On every `canvas_read`, Python computes:

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

### 4.5 Stage 3 — Compose the chart

Reads the finalised canvas and produces presentation: title, subtitle, axis labels, and
**captions with timestamps**.

Qwen has no strict-schema mode, so this is `response_format: {"type": "json_object"}`
**plus a validate-and-retry loop**:

1. System prompt states the exact JSON shape **and** the docs' requirement that the prompt
   itself instruct JSON output.
2. Parse. On `JSONDecodeError` or Pydantic failure, retry with the validation error
   appended as feedback. Cap at 3 attempts, then fail the run.
3. Validate semantics server-side regardless of whether parsing succeeded.

Target shape:

```jsonc
{
  "title": "string",
  "subtitle": "string",
  "xLabel": "string",
  "yLabel": "string",
  "currency": "string",
  "currencyPosition": "prefix" | "suffix",
  "captions": [{ "text": "string", "appearAt": 0.0, "duration": 0.0 }]
}
```

**Caption timing needs guarding.** The model can only place `appearAt` sensibly if we tell
it `animationDuration` and the per-series time range. Put both in the prompt, then
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
| `token`   | `{"text": "..."}` | Streamed prose during search turns |
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

Indicative `qwen3.7-plus` pricing — **verify in the console for your region**, published
figures vary by source and region (~$0.32/$1.28 and ~$0.40/$1.60 per MTok both appear):

| | Input | Output | Cache read |
|---|---|---|---|
| qwen3.7-plus | ~$0.32 /MTok | ~$1.28 /MTok | ~$0.064 /MTok |
| *(Opus 4.8, for reference)* | $5 /MTok | $25 /MTok | — |

Roughly **15× cheaper input, ~20× cheaper output** — the reason for the switch. Context is
1M with 131K max output, so the loop is not context-constrained.

- The research **loop** is still the cost driver: every iteration resends the conversation
  and search results are large.
- Use context caching for the system prompt + tool definitions. Keep the `canvas_*` tool
  schemas **byte-stable** — build them as module constants, never per-run.
- Keep volatile content (topic, language, run id) out of the cached prefix.
- Because the canvas is durable state, **old search results can be dropped from the
  transcript** once their rows are recorded. The canvas *is* the memory; the transcript is
  disposable. This is the main lever on loop cost.
- Cap search turns per run plus a per-run token budget so a bad topic can't run up a bill.

---

## 8. Phases

### Phase 0 — Restructure ✅ acceptance: app still runs
- [x] `git mv` frontend files into `/frontend` (`src`, `public`, `index.html`,
      `package.json`, `package-lock.json`, `vite.config.ts`, `tsconfig*.json`)
- [x] Update `.claude/launch.json` (cwd + port 5175 stays)
- [x] `npm run build` passes from `/frontend`; dev server serves the chart as before

### Phase 1 — Backend skeleton ✅ acceptance: `/api/health` returns ok
- [x] `uv init` in `/backend`, add `fastapi`, `uvicorn[standard]`, `dashscope`, `pydantic`
- [x] `main.py` with CORS for the Vite origin
- [x] Vite proxy `/api` → `http://localhost:8000`
- [x] `.env.example`; **`.env` and `.runs/` must be gitignored**
- [x] **Smoke test**: `backend/scripts/smoke_dashscope.py` — one DashScope native call
      with `enable_search` + `enable_source`; asserts `search_info.search_results` is
      populated. Confirms region + model + key before anything is built on top.
      ⚠️ Written and runnable, but **not yet executed against a live key** — run it
      before starting Phase 3.

### Phase 2 — The canvas ✅ acceptance: unit tests, no model involved
- [ ] `store.py` — append / revise / drop / persist to CSV
- [ ] `derive.py` — period parsing, unit conversion, conflict detection
- [ ] Gap report computation
- [ ] URL cross-validation against a retrieved-URL set
- [ ] Tests: mixed units, unparseable period, conflicting sources, fabricated URL

### Phase 3 — Stage 1 research loop ✅ acceptance: real sources, gaps closing
- [ ] 🔬 Spike: does `enable_search` + `tools` work in one request?
- [ ] Search turn (`forced_search: true`) → harvest `search_info.search_results`
- [ ] Extract turn with `canvas_append_rows`
- [ ] Loop bounds: iterations, search turns, tokens
- [ ] SSE `token` / `canvas` / `sources` events

### Phase 4 — Stage 3 compose ✅ acceptance: valid ChartConfig, captions in range
- [ ] `json_object` response format + validate-and-retry (cap 3)
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
- [ ] Transcript trimming once rows are persisted
- [ ] Typed error handling + retry on rate limits
- [ ] Caching verified against reported cache-hit tokens

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
- Because the model types `source_url`, it is cross-validated against actually-returned
  search URLs (§4.2).

> ⚠️ `DataPoint` in `frontend/src/types.ts` is `{time, label, value}` — there is **no**
> source field, and adding one changes the shape the renderer consumes. Provenance lives
> in the canvas and travels over the `sources` SSE event; the renderer still receives an
> unchanged `ChartConfig`.

### 9.3 Canvas is the source of truth ✅

Once a row is in the canvas it's durable state; the conversation transcript is disposable.
This is what allows transcript trimming on long loops, resuming a failed run, and
downloading the evidence behind any chart. It's also what made switching providers cheap.

---

## 10. Open questions

1. **Failure mode** — if research finds no usable numbers, fail loudly or return a
   partial chart? Recommend failing loudly.
2. **Series icons** — `Series.image` (the endpoint logo) has no automatic source. Leave
   empty, or attempt favicon lookup from the cited domain?
3. **Rate limits** — single-user local, or deployed and shared?
4. **Canvas reuse across runs** — should a new topic start empty, or can a user re-open a
   previous run's canvas and extend it? Affects whether `run_id` is user-visible.
5. **Full article text** — search snippets only, or add a fetcher for the cited URLs?
   Snippets may not contain the specific figure. Check whether the Responses API's
   `web_extractor` covers this before building one.

---

## 11. Reference — Qwen / DashScope shapes

| Thing | Correct form |
|---|---|
| Endpoint | `dashscope-intl.aliyuncs.com` (intl) / `dashscope.aliyuncs.com` (CN) — model availability differs |
| API surface | **DashScope native.** OpenAI-compatible does **not** return search sources |
| SDK | `dashscope` Python package (not `openai`) |
| Enable search | `enable_search: true` + `search_options: {...}` |
| Sources | `response.output.search_info["search_results"]` → `{index, title, url, site_name, icon}` |
| Citations | `search_options.enable_citation: true`, `citation_format: "[<number>]"` |
| Force a search | `search_options.forced_search: true` — otherwise it may answer from memory |
| Search strategy | `turbo` (default) / `max` / `agent` / `agent_max` |
| JSON output | `response_format: {"type": "json_object"}` — **and the prompt must also instruct JSON** |
| Strict schema | ❌ none — use validate-and-retry |
| Function calling | `tools` + `tool_choice: "auto"` |
| Search + tools together | ⚠️ unverified — §4.1 alternates turns to avoid depending on it |

**Doc sources:**
[Web search with large models](https://www.alibabacloud.com/help/en/model-studio/web-search) ·
[DashScope API reference](https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-dashscope) ·
[Function calling](https://www.alibabacloud.com/help/en/model-studio/qwen-function-calling) ·
[OpenAI-compatible mode](https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope)
