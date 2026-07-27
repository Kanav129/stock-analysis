# Desk job queue + front-page progress

**Date:** 2026-07-27  
**Status:** Approved  
**Scope:** Durable LLM job queue (per-ticker), concurrency limit, cancel, Dashboard Jobs panel; sync remains separate but visible

## Goals

1. Show all in-flight desk activity on the front page (sync + LLM jobs).
2. Cap concurrent LLM jobs (`JOB_MAX_CONCURRENT`, default 1); queue the rest.
3. Cancel: queued drops immediately; running soft-stops after the current step.
4. Survive Render restarts via Postgres; heal interrupted runs and resume the queue.

## Decisions

| Topic | Choice |
|-------|--------|
| Concurrency pool | LLM only (`core_analysis`, `deep_dive`, `rescore`); sync separate |
| Desk Run analysis | One job per ticker |
| Cancel | Soft for running; instant for queued |
| Persistence | `desk_jobs` table; auto-resume after heal |
| UI | Jobs panel: sync row when active + LLM running/queued |

## Architecture

- `JobQueueService` owns enqueue/claim/cancel/worker.
- Sync stays on `SyncService`; `GET /jobs` merges sync status for the UI.
- Analysis/research/cron entry points enqueue instead of starting unbounded work.

## Data model (`desk_jobs`)

- `id` UUID, `job_type`, `ticker`, `status` (`queued`|`running`|`done`|`failed`|`cancelled`|`interrupted`)
- `cancel_requested`, `progress` JSONB, `result` JSONB, `error`
- `created_at`, `started_at`, `finished_at`, `updated_at`

## API

- `GET /jobs` — `{ sync, jobs, limits }`
- `POST /jobs` — `{ job_type, tickers[], force? }`
- `POST /jobs/{id}/cancel`, `POST /jobs/cancel-all`

## Frontend

- `JobsPanel` on Dashboard; poll while active; keepalive includes jobs.
- Stock detail Generate/Deep dive enqueue through the same queue.

## Non-goals

- Sync in the concurrency pool
- External Redis workers
- Kronos deps on free Render
