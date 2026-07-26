# Login-page backend wake (Render free tier)

**Date:** 2026-07-26  
**Status:** Approved  
**Scope:** Frontend login page only — wake sleeping Render free dyno before auth submit

## Problem

On Render free tier, the API spins down after idle. Visiting the site after a long gap means the first login request waits ~30–60s for cold start, so sign-in feels stuck.

## Goals

1. As soon as an unauthenticated user lands on `/login`, ping the backend so cold start begins while they type the access key.
2. Show soft status (informational only): waking → ready, or a “taking longer” message after a deadline.
3. Never block login — submit always works.

## Non-goals

- New backend endpoints (reuse `GET /health`).
- Waking from app root for already-logged-in sessions.
- Gating or disabling the login button.
- Changing `useSyncKeepAlive` (that stays for long-running jobs after login).

## Decisions

| Topic | Choice |
|-------|--------|
| UX | Soft status under the form; login always enabled |
| Retry | Retry until ready, or until ~90s wall clock |
| Endpoint | Existing unauthenticated `GET /health` via `api.health()` |
| Placement | Login page mount only |

## Approach

**Login-page hook + existing `/health`.**

Add `useBackendWake()` used by `LoginPage`:

1. On mount, set status `waking` and call `api.health()`.
2. On success → `ready`.
3. On failure → wait ~3s and retry while under the 90s deadline.
4. If deadline elapses without success → `slow` and stop retrying.
5. On unmount, stop updating state / stop scheduling retries (cancelled flag). Each attempt is raced against remaining deadline so a hung request cannot block the UI forever.
6. Copy:
   - `waking`: “Waking desk…”
   - `ready`: “Desk ready”
   - `slow`: “Taking longer than usual — try signing in anyway”

## Architecture

```
LoginPage mounts
    → useBackendWake()
        → loop: api.health() until ok or 90s
        → status for muted label under form
User may submit login at any time (independent of wake status)
```

No backend changes. `/health` remains public (already in auth allowlist).

## Components

| Unit | Responsibility |
|------|----------------|
| `frontend/src/hooks/useBackendWake.ts` | Wake loop + status state |
| `frontend/src/pages/LoginPage.tsx` | Call hook; render muted status under form |

## Error handling

- Health failures are expected during cold start; retry quietly.
- After 90s without success, show `slow` copy; do not spam further retries.
- Unmount cancels further state updates.

## Testing

No frontend test runner in repo. Verify manually:

1. With API down or sleeping: open `/login` → “Waking desk…” appears; after wake → “Desk ready”.
2. Login submit works while status is still “Waking desk…”.
3. Leave login before ready: no console errors / no stuck updates.
4. Local always-on API: status should flip to “Desk ready” quickly.
