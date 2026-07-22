# Resume + once-per-day gate for sync & analysis

**Date:** 2026-07-22  
**Status:** Approved  
**Scope:** Daily news/price sync and core-report analysis (manual UI + GitHub cron)

## Problem

Long Render free-tier jobs often die mid-run (timeouts, dyno sleep, deploys). Today, progress lives only in process memory, so a retry re-runs the full universe and wastes Yahoo / LLM / API quota. There is also no once-per-day guard, so accidental double-clicks or overlapping cron + manual runs repeat completed work.

## Goals

1. **Resume** — a new run continues from the last successful ticker/stage for today (HKT).
2. **Soft once-per-day limit** — if the day is fully complete, warn in the UI and no-op cron; allow an intentional “Run again” (`force: true`).
3. **Survive restarts** — checkpoints persist in Postgres (`app_settings`), not RAM.

## Non-goals

- Changing scraper internals beyond accepting a filtered ticker list.
- Once-per-day limits on **rescore** or single-ticker research report generation.
- Exact minute-level SLA; day boundary is calendar HKT only.

## Decisions (from product Q&A)

| Topic | Choice |
|-------|--------|
| Already completed today | Soft block — UI warning + optional force rerun |
| Partial run | Always resume (no “start fresh” choice in v1 except via `force`) |
| GitHub cron | Same gate — completed day → success no-op |
| Day boundary | `Asia/Hong_Kong` |

## Approach

**Primary:** durable checkpoints in `app_settings`.  
**Hybrid for analysis:** also skip tickers that already have a `stock_reports` core row with `created_at` in today’s HKT window (self-heals a missing checkpoint).

Prices cannot be inferred reliably from `stock_data.bar_ts` (market time ≠ sync time), so price resume is checkpoint-only.

## Data model

Keys in `app_settings` (JSON string values):

### `daily_sync:YYYY-MM-DD`

```json
{
  "status": "running|partial|completed|error",
  "tickers": ["AAPL", "…"],
  "news_done": ["AAPL"],
  "prices_done": ["AAPL"],
  "vectors_done": false,
  "errors": [{"ticker": "MELI", "error": "…"}],
  "started_at": "ISO-8601",
  "updated_at": "ISO-8601",
  "finished_at": null
}
```

### `daily_analysis:YYYY-MM-DD`

```json
{
  "status": "running|partial|completed|failed|cancelled",
  "mode": "core_report",
  "tickers": ["AAPL", "…"],
  "completed": [{"ticker": "AAPL", "rating": "…", "score": 0, "report_id": 1}],
  "errors": [],
  "started_at": "ISO-8601",
  "updated_at": "ISO-8601",
  "finished_at": null
}
```

Optional convenience keys (denormalized for UI): `last_sync_date`, `last_analysis_date` = HKT `YYYY-MM-DD` when status becomes `completed`.

Timezone helper: `APP_TIMEZONE` env default `Asia/Hong_Kong`.

## Backend behavior

### Sync `start(tickers=None, force=False)`

1. If already running → `{started: false}` (unchanged).
2. Load checkpoint for today (HKT). Build `universe` (explicit tickers or `UniverseService`).
3. **Completed gate:** if `status == completed` and every universe ticker is in both `news_done` and `prices_done` and `vectors_done`, and not `force` →  
   `{started: false, reason: "already_completed_today", date, finished_at, message}`.
4. Else **resume:**  
   - `news_todo = universe - news_done`  
   - `prices_todo = universe - prices_done`  
   - If news empty → skip to prices; if prices empty → vectors only if not `vectors_done`.
5. Set checkpoint `status=running`, persist after each successful ticker append to `news_done` / `prices_done`.
6. On stage/job failure or timeout → `status=partial` or `error`, keep done lists.
7. On full success → `status=completed`, set `_last_sync`, `last_sync_date`.
8. `force=true` ignores the completed gate and **clears** today’s done lists (true fresh rerun). Partial resume remains the default without force.

Response extras: `resumed`, `skipped: {news, prices}`, `reason`, `date`, `checkpoint`.

### Analysis `start(tickers=None, force=False)` (core only)

Same pattern. Done set = checkpoint `completed` tickers ∪ tickers with core `stock_reports.created_at` in today’s HKT window.  
`force` clears checkpoint completed list for today (DB reports still exist; force means “generate again” for all requested tickers).

Rescore endpoints unchanged by this gate.

### Cron

`POST /cron/sync` and `POST /cron/analyze` call `start(force=False)`.  
If `already_completed_today`, return HTTP 200 with `started: false` and `reason` so GitHub Actions treats it as success (workflow must not exit 1 on that reason).

Update workflows: after start, if `reason == already_completed_today`, exit 0 with a clear log line; if `started` or resumed, poll as today.

## Frontend

### Soft warning (integrated, not a modal)

On Desk / wherever Sync and Run Analysis live:

- Poll (or include in status) whether today is complete / partial.
- **Completed today:** muted inline notice under the button, e.g. `Completed today · 09:14 HKT`. Button label becomes **Run again**; click sends `{force: true}` (no modal). Banner may briefly note that this re-runs everything for today.
- **Partial today:** primary stays **Sync** / **Run analysis** with subtitle `Resuming · 12/22 prices left`. Click resumes (no `force`).
- Use existing Panel / muted text tokens (terminal desk aesthetic); no modal dialogs.

### Status API

Extend `GET /sync/status` and `GET /analysis/status` (or small `GET /runs/today`) with:

```json
{
  "daily": {
    "date": "2026-07-22",
    "timezone": "Asia/Hong_Kong",
    "status": "completed|partial|idle|running|error",
    "can_resume": true,
    "already_completed_today": false,
    "news_done_count": 22,
    "prices_done_count": 12,
    "finished_at": null
  }
}
```

Prefer embedding under existing status payloads to avoid extra round-trips.

## Edge cases

| Case | Behavior |
|------|----------|
| Dyno sleep mid-ticker | That ticker not in `*_done` → retried |
| News scrape returns 0 articles | Still mark news done for ticker (attempt succeeded) |
| Price scrape exception | Do not mark prices done |
| Vectors fail | Keep `vectors_done=false`; sync not `completed` until vectors OK |
| Universe grows mid-day | New tickers not in done lists → remaining work; completed only if all **current** universe tickers covered |
| Weekend / empty bars | Checkpoint still advances; do not use `bar_ts` for gates |
| Concurrent start | Existing “already running” lock wins |

## Files to change

- `services/run_checkpoint_service.py` (new) — load/save JSON checkpoints, HKT date helpers  
- `services/sync_service.py` — gate, resume, persist per ticker  
- `services/analysis_service.py` — gate, resume, DB hybrid skip  
- `rest_api/routes/sync_routes.py`, `analysis_routes.py`, `cron_routes.py` — accept `force`  
- `.github/workflows/daily-sync.yml`, `weekly-analysis.yml` — treat `already_completed_today` as success  
- `frontend` Sync/Analysis buttons + progress/status types  
- `.env.example` — `APP_TIMEZONE=Asia/Hong_Kong`

## Testing

- Unit: HKT day bounds; resume filters; completed gate with/without force; universe growth.  
- Integration (optional): checkpoint round-trip via `app_settings`.  
- Manual: kill mid-sync → restart → only remaining tickers; completed day → UI warning → force re-runs.

## Success criteria

1. Mid-run failure + manual/cron retry does not redo finished tickers/stages for that HKT day.  
2. Fully completed day: cron no-ops; UI shows integrated warning; force still works.  
3. Checkpoints survive Render restart/sleep.
