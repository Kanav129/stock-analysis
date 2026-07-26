# Login Backend Wake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On `/login` mount, ping `GET /health` with retries and soft status so Render free dynos start waking before the user submits their access key.

**Architecture:** New `useBackendWake` hook owns the retry loop and status; `LoginPage` displays muted copy. Reuses existing `api.health()` — no backend changes.

**Tech Stack:** React 19, TypeScript, existing Vite frontend `api` client

## Global Constraints

- Soft status only — never disable login submit based on wake status
- Retry until ready or 90s wall clock; ~3s between failed attempts
- Copy exactly: “Waking desk…”, “Desk ready”, “Taking longer than usual — try signing in anyway”
- Cancel on unmount (no state updates after teardown)

---

### Task 1: `useBackendWake` hook

**Files:**
- Create: `frontend/src/hooks/useBackendWake.ts`
- Consumes: `api.health()` from `frontend/src/api/client.ts`
- Produces: `useBackendWake(): 'waking' | 'ready' | 'slow'`

- [x] **Step 1: Create the hook**

```ts
import { useEffect, useState } from 'react';
import { api } from '../api/client';

export type BackendWakeStatus = 'waking' | 'ready' | 'slow';

const DEADLINE_MS = 90_000;
const RETRY_MS = 3_000;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

/**
 * Ping /health on mount so a sleeping Render free dyno starts booting
 * while the user is still on the login page.
 */
export function useBackendWake(): BackendWakeStatus {
  const [status, setStatus] = useState<BackendWakeStatus>('waking');

  useEffect(() => {
    let cancelled = false;
    const startedAt = Date.now();

    async function wake() {
      while (!cancelled) {
        const remaining = DEADLINE_MS - (Date.now() - startedAt);
        if (remaining <= 0) {
          setStatus('slow');
          return;
        }

        try {
          await Promise.race([
            api.health(),
            sleep(remaining).then(() => {
              throw new Error('wake-deadline');
            }),
          ]);
          if (!cancelled) setStatus('ready');
          return;
        } catch {
          if (cancelled) return;
          if (Date.now() - startedAt >= DEADLINE_MS) {
            setStatus('slow');
            return;
          }
          await sleep(RETRY_MS);
        }
      }
    }

    void wake();
    return () => {
      cancelled = true;
    };
  }, []);

  return status;
}
```

- [x] **Step 2: Confirm TypeScript accepts the file**

Run: `cd frontend && npx tsc -b --pretty false`
Expected: no errors related to `useBackendWake.ts`

---

### Task 2: Wire soft status into `LoginPage`

**Files:**
- Modify: `frontend/src/pages/LoginPage.tsx`
- Consumes: `useBackendWake()` from Task 1

- [x] **Step 1: Import hook and map status to copy**

Add import and call at top of `LoginPage` (before early `isLoggedIn` return is fine — hooks must run unconditionally; call hook before the redirect return).

```tsx
import { useBackendWake } from '../hooks/useBackendWake';

// inside LoginPage, before any conditional return:
const wakeStatus = useBackendWake();

const wakeLabel =
  wakeStatus === 'ready'
    ? 'Desk ready'
    : wakeStatus === 'slow'
      ? 'Taking longer than usual — try signing in anyway'
      : 'Waking desk…';
```

Important: call `useBackendWake()` **before** `if (isLoggedIn()) return <Navigate …>` so Rules of Hooks are satisfied.

- [x] **Step 2: Render muted status under the form**

After the submit button (still inside the form or just below it), add:

```tsx
<p
  className="mt-3 text-center text-xs text-[var(--color-text-muted)]"
  aria-live="polite"
>
  {wakeLabel}
</p>
```

Do not disable the button based on `wakeStatus`.

- [x] **Step 3: Build frontend**

Run: `cd frontend && npm run build`
Expected: success

---

### Task 3: Manual check

- [x] **Step 1: Smoke-check locally** (build verified; manual UI check left to you)

With API running: open `/login` → label should become “Desk ready” quickly; submit still works.

Optional: stop API → open `/login` → “Waking desk…” then after ~90s “Taking longer than usual…”.
