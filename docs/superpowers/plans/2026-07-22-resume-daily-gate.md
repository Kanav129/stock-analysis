# Resume + Daily Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist HKT-day sync/analysis checkpoints in `app_settings`, resume unfinished tickers/stages on restart, soft-block completed days (UI warning + cron no-op) while allowing `force: true` full reruns.

**Architecture:** A small `RunCheckpointService` owns timezone helpers and JSON checkpoint load/save in Postgres `app_settings`. `SyncService` and `AnalysisService` call it on start and after each successful ticker/stage. Scrapers gain an `on_ticker_done` callback so checkpoints update mid-run. Status APIs embed a `daily` summary for the frontend soft warning.

**Tech Stack:** Python 3.11 (`zoneinfo`), FastAPI, Postgres `app_settings`, React + TanStack Query, GitHub Actions curl workflows.

**Spec:** `docs/superpowers/specs/2026-07-22-resume-daily-gate-design.md`

## Global Constraints

- Day boundary timezone: `Asia/Hong_Kong` (overridable via `APP_TIMEZONE`).
- Soft once-per-day gate: warn / no-op cron; allow `force: true`.
- Always resume partial runs (no separate “start fresh” except `force`).
- Price resume is checkpoint-only (never infer from `stock_data.bar_ts`).
- Analysis hybrid skip: checkpoint ∪ core `stock_reports.created_at` in today’s HKT window.
- Rescore and single-ticker research generation are out of scope for this gate.
- Sync is not `completed` until vectors succeed (`vectors_done=true`).
- Cron must return HTTP 200 with `reason: already_completed_today` (not fail the workflow).

---

## File structure

| File | Responsibility |
|------|----------------|
| `services/run_checkpoint_service.py` | HKT date helpers; load/save sync & analysis checkpoints; `daily_summary()` for status payloads |
| `services/tests/test_run_checkpoint_service.py` | Unit tests for timezone + pure helpers (mocked DB) |
| `services/tests/test_sync_resume.py` | Unit tests for sync gate/resume todo computation |
| `services/tests/test_analysis_resume.py` | Unit tests for analysis done-set / force clear |
| `scraper/news_scraper.py` | Call `on_ticker_done(ticker)` after each ticker attempt finishes |
| `scraper/stock_data_scraper.py` | Call `on_ticker_done(ticker)` only after successful scrape |
| `services/sync_service.py` | `force`, gate, resume lists, checkpoint writes, `daily` on status |
| `services/analysis_service.py` | Same for core analysis + DB hybrid skip |
| `rest_api/schemas.py` | `force: bool = False` on sync/analysis request models |
| `rest_api/routes/sync_routes.py` | Pass `force`; use shared schema |
| `rest_api/routes/analysis_routes.py` | Pass `force` |
| `rest_api/routes/cron_routes.py` | Call `start(force=False)` (explicit) |
| `.github/workflows/daily-sync.yml` | Exit 0 on `already_completed_today` |
| `.github/workflows/weekly-analysis.yml` | Same |
| `frontend/src/api/types.ts` | `DailyRunSummary` + extend progress types |
| `frontend/src/api/client.ts` | `force` on `syncData` / `runAnalysis` |
| `frontend/src/components/SyncDataButton.tsx` | Soft warning + Run again |
| `frontend/src/components/RunAnalysisButton.tsx` | Soft warning + Run again |
| `.env.example` | Document `APP_TIMEZONE` |

---

### Task 1: Checkpoint service (timezone + persistence helpers)

**Files:**
- Create: `services/run_checkpoint_service.py`
- Create: `services/tests/test_run_checkpoint_service.py`
- Modify: `.env.example` (add `APP_TIMEZONE` near deployment section)

**Interfaces:**
- Produces:
  - `app_timezone() -> ZoneInfo`
  - `today_key() -> str`  # `YYYY-MM-DD` in app TZ
  - `day_bounds_utc(day: str | None = None) -> tuple[datetime, datetime]`  # aware UTC inclusive start, exclusive end
  - `sync_key(day: str | None = None) -> str`  # `daily_sync:YYYY-MM-DD`
  - `analysis_key(day: str | None = None) -> str`
  - `empty_sync_checkpoint(tickers: list[str]) -> dict`
  - `empty_analysis_checkpoint(tickers: list[str]) -> dict`
  - `load_json(key: str) -> dict | None`
  - `save_json(key: str, value: dict) -> None`
  - `load_sync(day: str | None = None) -> dict | None`
  - `save_sync(data: dict, day: str | None = None) -> None`
  - `load_analysis(day: str | None = None) -> dict | None`
  - `save_analysis(data: dict, day: str | None = None) -> None`
  - `mark_last_sync_date(day: str | None = None) -> None`  # sets `last_sync_date`
  - `mark_last_analysis_date(day: str | None = None) -> None`
  - `is_sync_complete_for_universe(cp: dict | None, universe: list[str]) -> bool`
  - `sync_todos(cp: dict | None, universe: list[str], *, force: bool) -> dict` with keys `news_todo`, `prices_todo`, `need_vectors`, `resumed`, `cleared`
  - `daily_sync_summary(cp: dict | None, universe: list[str] | None = None) -> dict`
  - `daily_analysis_summary(cp: dict | None, universe: list[str] | None = None) -> dict`
  - Module singleton: `run_checkpoints = RunCheckpointService()` (or plain functions — prefer a class with no process state beyond DB)

- [ ] **Step 1: Write failing tests**

Create `services/tests/__init__.py` if missing. Create `services/tests/test_run_checkpoint_service.py`:

```python
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from services import run_checkpoint_service as rcs


def test_today_key_uses_hkt_not_utc():
    # 2026-07-21 20:30 UTC == 2026-07-22 04:30 HKT
    fixed = datetime(2026, 7, 21, 20, 30, tzinfo=timezone.utc)
    with patch.object(rcs, "_now_utc", return_value=fixed):
        with patch.dict("os.environ", {"APP_TIMEZONE": "Asia/Hong_Kong"}, clear=False):
            assert rcs.today_key() == "2026-07-22"


def test_day_bounds_utc_hkt():
    start, end = rcs.day_bounds_utc("2026-07-22")
    assert start == datetime(2026, 7, 21, 16, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 7, 22, 16, 0, tzinfo=timezone.utc)


def test_is_sync_complete_requires_vectors_and_all_tickers():
    universe = ["AAPL", "MSFT"]
    cp = {
        "status": "completed",
        "news_done": ["AAPL", "MSFT"],
        "prices_done": ["AAPL", "MSFT"],
        "vectors_done": False,
    }
    assert rcs.is_sync_complete_for_universe(cp, universe) is False
    cp["vectors_done"] = True
    assert rcs.is_sync_complete_for_universe(cp, universe) is True
    # Universe grew
    assert rcs.is_sync_complete_for_universe(cp, ["AAPL", "MSFT", "NVDA"]) is False


def test_sync_todos_resume_and_force():
    universe = ["AAPL", "MSFT", "NVDA"]
    cp = {
        "status": "partial",
        "news_done": ["AAPL", "MSFT"],
        "prices_done": ["AAPL"],
        "vectors_done": False,
    }
    todos = rcs.sync_todos(cp, universe, force=False)
    assert todos["news_todo"] == ["NVDA"]
    assert todos["prices_todo"] == ["MSFT", "NVDA"]
    assert todos["need_vectors"] is True
    assert todos["resumed"] is True

    forced = rcs.sync_todos(cp, universe, force=True)
    assert forced["news_todo"] == universe
    assert forced["prices_todo"] == universe
    assert forced["cleared"] is True


def test_save_json_upserts_app_settings():
    db = MagicMock()
    with patch("services.run_checkpoint_service.get_db_client", return_value=db):
        rcs.save_json("daily_sync:2026-07-22", {"status": "running", "news_done": []})
    db.execute_query.assert_called_once()
    sql, params = db.execute_query.call_args[0]
    assert "INSERT INTO app_settings" in sql
    assert params[0] == "daily_sync:2026-07-22"
    assert '"status": "running"' in params[1] or '"status":"running"' in params[1].replace(" ", "")
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest services/tests/test_run_checkpoint_service.py -v
```

Expected: import/collection failure or `AttributeError` (module missing).

- [ ] **Step 3: Implement `services/run_checkpoint_service.py`**

```python
"""Durable daily sync/analysis checkpoints in app_settings (HKT day keys)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from db.db_factory import get_db_client


def app_timezone() -> ZoneInfo:
    return ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Hong_Kong"))


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def today_key() -> str:
    return _now_utc().astimezone(app_timezone()).date().isoformat()


def day_bounds_utc(day: str | None = None) -> tuple[datetime, datetime]:
    """Return [start, end) in UTC for the given HKT calendar day."""
    day = day or today_key()
    tz = app_timezone()
    y, m, d = (int(x) for x in day.split("-"))
    start_local = datetime(y, m, d, 0, 0, 0, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def sync_key(day: str | None = None) -> str:
    return f"daily_sync:{day or today_key()}"


def analysis_key(day: str | None = None) -> str:
    return f"daily_analysis:{day or today_key()}"


def empty_sync_checkpoint(tickers: list[str]) -> dict[str, Any]:
    now = _now_utc().isoformat()
    return {
        "status": "running",
        "tickers": list(tickers),
        "news_done": [],
        "prices_done": [],
        "vectors_done": False,
        "errors": [],
        "started_at": now,
        "updated_at": now,
        "finished_at": None,
    }


def empty_analysis_checkpoint(tickers: list[str]) -> dict[str, Any]:
    now = _now_utc().isoformat()
    return {
        "status": "running",
        "mode": "core_report",
        "tickers": list(tickers),
        "completed": [],
        "errors": [],
        "started_at": now,
        "updated_at": now,
        "finished_at": None,
    }


def load_json(key: str) -> dict | None:
    db = get_db_client()
    try:
        rows, _ = db.fetch_query(
            "SELECT value FROM app_settings WHERE key = %s",
            (key,),
        )
        if not rows:
            return None
        raw = rows[0][0]
        if not raw:
            return None
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def save_json(key: str, value: dict) -> None:
    payload = dict(value)
    payload["updated_at"] = _now_utc().isoformat()
    db = get_db_client()
    db.execute_query(
        """
        INSERT INTO app_settings (key, value, updated_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
        """,
        (key, json.dumps(payload)),
    )


def load_sync(day: str | None = None) -> dict | None:
    return load_json(sync_key(day))


def save_sync(data: dict, day: str | None = None) -> None:
    save_json(sync_key(day), data)


def load_analysis(day: str | None = None) -> dict | None:
    return load_json(analysis_key(day))


def save_analysis(data: dict, day: str | None = None) -> None:
    save_json(analysis_key(day), data)


def mark_last_sync_date(day: str | None = None) -> None:
    save_json("last_sync_date", {"date": day or today_key()})


def mark_last_analysis_date(day: str | None = None) -> None:
    # Store plain string date for convenience readers; keep JSON object for consistency
    save_json("last_analysis_date", {"date": day or today_key()})


def is_sync_complete_for_universe(cp: dict | None, universe: list[str]) -> bool:
    if not cp or not universe:
        return False
    if not cp.get("vectors_done"):
        return False
    news = {t.upper() for t in (cp.get("news_done") or [])}
    prices = {t.upper() for t in (cp.get("prices_done") or [])}
    for t in universe:
        u = t.upper()
        if u not in news or u not in prices:
            return False
    return True


def sync_todos(
    cp: dict | None,
    universe: list[str],
    *,
    force: bool,
) -> dict[str, Any]:
    universe = [t.upper() for t in universe]
    if force or not cp:
        return {
            "news_todo": list(universe),
            "prices_todo": list(universe),
            "need_vectors": True,
            "resumed": False,
            "cleared": bool(force and cp),
        }
    news_done = {t.upper() for t in (cp.get("news_done") or [])}
    prices_done = {t.upper() for t in (cp.get("prices_done") or [])}
    news_todo = [t for t in universe if t not in news_done]
    prices_todo = [t for t in universe if t not in prices_done]
    need_vectors = not bool(cp.get("vectors_done"))
    resumed = bool(news_done or prices_done or cp.get("vectors_done")) and (
        bool(news_todo) or bool(prices_todo) or need_vectors
    )
    return {
        "news_todo": news_todo,
        "prices_todo": prices_todo,
        "need_vectors": need_vectors,
        "resumed": resumed,
        "cleared": False,
    }


def daily_sync_summary(cp: dict | None, universe: list[str] | None = None) -> dict[str, Any]:
    day = today_key()
    tz_name = str(app_timezone())
    if not cp:
        return {
            "date": day,
            "timezone": tz_name,
            "status": "idle",
            "can_resume": False,
            "already_completed_today": False,
            "news_done_count": 0,
            "prices_done_count": 0,
            "finished_at": None,
        }
    universe = [t.upper() for t in (universe or cp.get("tickers") or [])]
    news_n = len(cp.get("news_done") or [])
    prices_n = len(cp.get("prices_done") or [])
    complete = is_sync_complete_for_universe(cp, universe) if universe else (
        cp.get("status") == "completed" and bool(cp.get("vectors_done"))
    )
    status = cp.get("status") or "idle"
    if complete:
        status = "completed"
    elif news_n or prices_n or status in ("partial", "error", "running"):
        if status == "running":
            pass
        elif status not in ("error",):
            status = "partial" if (news_n or prices_n) else status
    can_resume = (not complete) and (news_n > 0 or prices_n > 0 or status in ("partial", "error"))
    return {
        "date": day,
        "timezone": tz_name,
        "status": status,
        "can_resume": bool(can_resume),
        "already_completed_today": bool(complete),
        "news_done_count": news_n,
        "prices_done_count": prices_n,
        "finished_at": cp.get("finished_at"),
    }


def daily_analysis_summary(cp: dict | None, universe: list[str] | None = None) -> dict[str, Any]:
    day = today_key()
    tz_name = str(app_timezone())
    completed = cp.get("completed") or [] if cp else []
    done_tickers = {str(c.get("ticker", "")).upper() for c in completed if isinstance(c, dict)}
    universe = [t.upper() for t in (universe or (cp or {}).get("tickers") or [])]
    complete = bool(universe) and all(t in done_tickers for t in universe) and (
        (cp or {}).get("status") in ("completed", "done")
    )
    # Also treat full coverage as complete even if status lagging
    if universe and all(t in done_tickers for t in universe) and done_tickers:
        complete = True
    status = (cp or {}).get("status") or "idle"
    if complete:
        status = "completed"
    elif done_tickers and not complete:
        status = "partial" if status not in ("running", "failed", "cancelled") else status
    return {
        "date": day,
        "timezone": tz_name,
        "status": status,
        "can_resume": bool(done_tickers) and not complete,
        "already_completed_today": bool(complete),
        "completed_count": len(done_tickers),
        "finished_at": (cp or {}).get("finished_at"),
    }
```

Do **not** require `status == "completed"` for the sync gate — coverage + `vectors_done` is enough so a crashed worker that finished all work but failed to flip status still soft-blocks. When marking success in SyncService, still set `status="completed"`.

Add to `.env.example` under deployment:

```bash
# Calendar day for sync/analysis checkpoints (resume + once-per-day soft gate)
APP_TIMEZONE=Asia/Hong_Kong
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest services/tests/test_run_checkpoint_service.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add services/run_checkpoint_service.py services/tests/test_run_checkpoint_service.py services/tests/__init__.py .env.example
git commit -m "$(cat <<'EOF'
Add HKT daily run checkpoint helpers in app_settings.

EOF
)"
```

---

### Task 2: Scraper `on_ticker_done` hooks

**Files:**
- Modify: `scraper/news_scraper.py` (`scrape_all_tickers`)
- Modify: `scraper/stock_data_scraper.py` (`scrape_all_tickers`)
- Test: extend `scraper/tests/test_stock_data_scraper.py`; add news callback assertion if easy

**Interfaces:**
- Consumes: existing `on_progress(ticker, index, total)`
- Produces: optional `on_ticker_done: Callable[[str], None] | None` — news: after each ticker finishes (success or caught error); prices: only after successful `scrape_ticker`

- [ ] **Step 1: Write failing test**

In `scraper/tests/test_stock_data_scraper.py` add (same patch target as existing `test_scrape_all_tickers`):

```python
@patch.object(StockDataScraper, "scrape_ticker")
def test_on_ticker_done_skips_failed_price(mock_scrape):
    done: list[str] = []
    mock_scrape.side_effect = [{"ok": True}, Exception("fail"), {"ok": True}]
    StockDataScraper().scrape_all_tickers(
        ["AAPL", "MSFT", "NVDA"],
        on_ticker_done=lambda t: done.append(t),
    )
    assert done == ["AAPL", "NVDA"]
```

- [ ] **Step 2: Run test — expect FAIL** (unexpected kwarg / not called)

```bash
pytest scraper/tests/test_stock_data_scraper.py::test_on_ticker_done_skips_failed_price -v
```

- [ ] **Step 3: Implement hooks**

News (`scraper/news_scraper.py`):

```python
def scrape_all_tickers(self, tickers, on_progress=None, on_ticker_done=None):
    total = len(tickers)
    for index, ticker in enumerate(tickers, start=1):
        logger.info(f"Scraping news for ticker: {ticker} ({index}/{total})")
        if on_progress:
            try:
                on_progress(ticker, index, total)
            except Exception:
                pass
        try:
            self.scrape_articles(ticker)
        except Exception as e:
            logger.error(f"Error while scraping news for {ticker}: {e}")
        if on_ticker_done:
            try:
                on_ticker_done(ticker)
            except Exception:
                pass
```

Prices (`scraper/stock_data_scraper.py`):

```python
def scrape_all_tickers(
    self,
    tickers: list[str],
    on_progress: Optional[Callable[[str, int, int], None]] = None,
    on_ticker_done: Optional[Callable[[str], None]] = None,
) -> None:
    total = len(tickers)
    for index, ticker in enumerate(tickers, start=1):
        try:
            logger.info(f"Syncing prices for {ticker} ({index}/{total})...")
            if on_progress:
                on_progress(ticker, index, total)
            result = self.scrape_ticker(ticker)
            logger.info(f"Price sync done for {ticker}: {result}")
            if on_ticker_done:
                on_ticker_done(ticker)
        except Exception as exc:
            logger.error(f"Error syncing prices for {ticker}: {exc}")
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest scraper/tests/test_stock_data_scraper.py -v
```

- [ ] **Step 5: Commit**

```bash
git add scraper/news_scraper.py scraper/stock_data_scraper.py scraper/tests/test_stock_data_scraper.py
git commit -m "$(cat <<'EOF'
Add on_ticker_done callbacks for sync checkpointing.

EOF
)"
```

---

### Task 3: SyncService gate, resume, and checkpoint writes

**Files:**
- Modify: `services/sync_service.py`
- Create: `services/tests/test_sync_resume.py`

**Interfaces:**
- Consumes: `run_checkpoint_service` helpers from Task 1; scraper hooks from Task 2
- Produces:
  - `start(tickers: list[str] | None = None, force: bool = False) -> dict`
  - On already complete: `{started: False, reason: "already_completed_today", date, finished_at, message, daily, ...status}`
  - On start: includes `resumed`, `skipped: {news: int, prices: int}`, `date`, `timeouts` based on **todo** sizes (news timeout from `len(news_todo)`, prices from `len(prices_todo)`, vectors 600 if `need_vectors` else 0)
  - `get_status()` includes `daily: daily_sync_summary(...)`

- [ ] **Step 1: Write failing unit tests for gate/todos wiring**

`services/tests/test_sync_resume.py` — test pure behavior by calling helpers already covered, plus a focused test of `start` with mocks:

```python
from unittest.mock import MagicMock, patch

from services.sync_service import SyncService


def test_start_returns_already_completed_today():
    svc = SyncService()
    universe = ["AAPL", "MSFT"]
    cp = {
        "status": "completed",
        "news_done": universe,
        "prices_done": universe,
        "vectors_done": True,
        "finished_at": "2026-07-22T01:00:00+00:00",
    }
    with patch.object(svc.universe, "get_tickers", return_value=universe):
        with patch("services.sync_service.rcs.load_sync", return_value=cp):
            with patch("services.sync_service.rcs.today_key", return_value="2026-07-22"):
                with patch("services.sync_service.rcs.is_sync_complete_for_universe", return_value=True):
                    result = svc.start(force=False)
    assert result["started"] is False
    assert result["reason"] == "already_completed_today"


def test_start_force_clears_and_starts(monkeypatch):
    svc = SyncService()
    universe = ["AAPL"]
    cp = {
        "status": "completed",
        "news_done": universe,
        "prices_done": universe,
        "vectors_done": True,
    }
    saved = {}

    def fake_save(data, day=None):
        saved["cp"] = data

    with patch.object(svc.universe, "get_tickers", return_value=universe):
        with patch("services.sync_service.rcs.load_sync", return_value=cp):
            with patch("services.sync_service.rcs.save_sync", side_effect=fake_save):
                with patch("services.sync_service.rcs.today_key", return_value="2026-07-22"):
                    with patch("services.sync_service.rcs.is_sync_complete_for_universe", return_value=True):
                        with patch("services.sync_service.rcs.sync_todos", return_value={
                            "news_todo": universe,
                            "prices_todo": universe,
                            "need_vectors": True,
                            "resumed": False,
                            "cleared": True,
                        }):
                            with patch("asyncio.get_running_loop") as loop:
                                loop.return_value.create_task = MagicMock()
                                result = svc.start(force=True)
    assert result["started"] is True
    assert saved["cp"]["news_done"] == []
```

Import alias in `sync_service.py`: `from services import run_checkpoint_service as rcs`.

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest services/tests/test_sync_resume.py -v
```

- [ ] **Step 3: Implement SyncService changes**

In `services/sync_service.py`:

1. Import `rcs`.
2. Change `start(self, tickers=None, force: bool = False)`.
3. After building `target` universe:
   - `cp = rcs.load_sync()`
   - If not force and `rcs.is_sync_complete_for_universe(cp, target)` → return already_completed payload (include `daily`).
   - `todos = rcs.sync_todos(cp, target, force=force)`
   - If force: `cp = rcs.empty_sync_checkpoint(target)` else reuse/merge: if no cp, empty; else set `status=running`, refresh `tickers=target`, keep done lists.
   - If `not todos["news_todo"] and not todos["prices_todo"] and not todos["need_vectors"]` → treat as complete gate (edge case).
   - Persist `rcs.save_sync(cp)`.
   - Compute timeouts with `compute_stage_timeouts` on max(1, len(news_todo)) / max(1, len(prices_todo)) — prefer a small local helper:

```python
def compute_resume_timeouts(news_n: int, prices_n: int, need_vectors: bool) -> dict[str, int]:
    base = compute_stage_timeouts(max(news_n, prices_n, 1))
    # Recompute stages from counts (mirror compute_stage_timeouts formula)
    ...
```

Simplest acceptable approach: call existing `compute_stage_timeouts(max(len(news_todo), len(prices_todo), 1))` then if not `need_vectors`, set `vectors=0` and shrink `total`. If a stage todo is empty, set that stage timeout to `0`.

4. Launch `_run_worker(target, news_todo, prices_todo, need_vectors, checkpoint_seed=cp)`.

5. In worker:
   - Run news only if `news_todo`; on each `on_ticker_done`, append to `cp["news_done"]` (dedupe) and `rcs.save_sync(cp)`.
   - Same for prices → `prices_done`.
   - Vectors: if `need_vectors`, run DocumentSyncManager; on success `cp["vectors_done"]=True`; on failure keep false, set `cp["status"]="partial"` or `"error"`, **do not** mark sync completed / `_last_sync`.
   - On full success: `cp["status"]="completed"`, `finished_at=...`, `rcs.save_sync`, `rcs.mark_last_sync_date()`, set `_last_sync`.
   - On timeout/exception: `cp["status"]="partial"` (or `"error"`), keep done lists, save.

6. `get_status`: attach `daily=rcs.daily_sync_summary(rcs.load_sync(), self._status.get("tickers") or None)`.

7. Fix current bug: chroma failure must not set in-memory `status="completed"` with 100% if vectors failed — align with checkpoint.

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest services/tests/test_sync_resume.py services/tests/test_run_checkpoint_service.py -v
```

- [ ] **Step 5: Commit**

```bash
git add services/sync_service.py services/tests/test_sync_resume.py
git commit -m "$(cat <<'EOF'
Resume daily sync from app_settings checkpoints.

EOF
)"
```

---

### Task 4: AnalysisService gate, hybrid skip, checkpoints

**Files:**
- Modify: `services/analysis_service.py`
- Create: `services/tests/test_analysis_resume.py`

**Interfaces:**
- Consumes: `rcs`; Postgres `stock_reports`
- Produces:
  - `start(tickers=None, force: bool = False) -> dict` with same `reason` / `resumed` / `skipped` patterns
  - `get_status()` includes `daily`
  - Helper `_core_reports_done_today() -> set[str]` querying:

```sql
SELECT DISTINCT ticker
FROM stock_reports
WHERE report_type = 'core'
  AND created_at >= %s
  AND created_at < %s
```

Use `day_bounds_utc()` for the two params (timezone-aware → pass as UTC datetimes; if DB stores naive UTC, convert with `.replace(tzinfo=None)` only if existing code does that — prefer passing timezone-aware and let psycopg adapt).

Done set for resume (when not force):  
`{c["ticker"].upper() for c in cp.get("completed") or []} | _core_reports_done_today()`  
`todo = [t for t in universe if t not in done]`

Completed gate: `todo` empty and not force → `already_completed_today`.

Force: clear checkpoint completed/errors via `empty_analysis_checkpoint(universe)` (still regenerate even if DB has today’s reports).

After each successful `_run_ticker_core_report`, append to checkpoint `completed` and `rcs.save_analysis`. On cancel/timeout/partial: `status=partial|cancelled|failed`. On full success with no remaining: `status=completed`, `mark_last_analysis_date`.

Map in-memory progress `status="done"` to checkpoint `"completed"` when persisting success (keep UI `done` if that breaks fewer clients — frontend already uses `done`).

- [ ] **Step 1: Write failing tests**

```python
from unittest.mock import patch

from services.analysis_service import AnalysisService


def test_analysis_todo_merges_checkpoint_and_db():
    universe = ["AAPL", "MSFT", "NVDA"]
    cp_done = {"AAPL"}
    db_done = {"MSFT"}
    done = cp_done | db_done
    todo = [t for t in universe if t not in done]
    assert todo == ["NVDA"]


def test_start_already_completed():
    AnalysisService._instance = None
    svc = AnalysisService()
    universe = ["AAPL", "MSFT"]
    with patch.object(svc.universe, "get_tickers", return_value=universe):
        with patch("services.analysis_service.rcs.load_analysis", return_value={
            "status": "completed",
            "completed": [{"ticker": "AAPL"}, {"ticker": "MSFT"}],
        }):
            with patch.object(svc, "_core_reports_done_today", return_value=set(universe)):
                with patch("services.analysis_service.rcs.today_key", return_value="2026-07-22"):
                    result = svc.start(force=False)
    assert result["started"] is False
    assert result["reason"] == "already_completed_today"
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest services/tests/test_analysis_resume.py -v
```

- [ ] **Step 3: Implement AnalysisService changes** (core `start` + `_run_worker` only; leave `start_rescore` untouched)

- [ ] **Step 4: Run — expect PASS**

```bash
pytest services/tests/test_analysis_resume.py services/tests/test_run_checkpoint_service.py -v
```

- [ ] **Step 5: Commit**

```bash
git add services/analysis_service.py services/tests/test_analysis_resume.py
git commit -m "$(cat <<'EOF'
Resume daily core analysis with hybrid checkpoint skip.

EOF
)"
```

---

### Task 5: API schemas and routes (`force` + daily on status)

**Files:**
- Modify: `rest_api/schemas.py` — add `force: bool = False` to `AnalysisRunRequest` and `SyncDataRequest`
- Modify: `rest_api/routes/sync_routes.py` — import `SyncDataRequest` from schemas; pass `force`
- Modify: `rest_api/routes/analysis_routes.py` — pass `force`
- Modify: `rest_api/routes/cron_routes.py` — `start(force=False)` explicit (document no-op reason in docstring)

- [ ] **Step 1: Update schemas**

```python
class AnalysisRunRequest(BaseModel):
    tickers: Optional[List[str]] = None
    force: bool = False


class SyncDataRequest(BaseModel):
    tickers: Optional[List[str]] = None
    force: bool = False
```

Remove duplicate `SyncDataRequest` class body from `sync_routes.py`; import from schemas.

- [ ] **Step 2: Wire routes**

```python
# sync_routes
tickers = body.tickers if body else None
force = body.force if body else False
return sync_service.start(tickers, force=force)

# analysis_routes
return analysis_service.start(tickers, force=body.force if body else False)

# cron_routes
return sync_service.start(force=False)
return analysis_service.start(force=False)
```

- [ ] **Step 3: Smoke-test import**

```bash
python -c "from rest_api.routes.sync_routes import sync_data; from rest_api.schemas import SyncDataRequest; print(SyncDataRequest(force=True))"
```

Expected: prints model with `force=True`.

- [ ] **Step 4: Commit**

```bash
git add rest_api/schemas.py rest_api/routes/sync_routes.py rest_api/routes/analysis_routes.py rest_api/routes/cron_routes.py
git commit -m "$(cat <<'EOF'
Accept force flag on sync and analysis start routes.

EOF
)"
```

---

### Task 6: GitHub Actions — treat completed day as success

**Files:**
- Modify: `.github/workflows/daily-sync.yml` (Start sync step)
- Modify: `.github/workflows/weekly-analysis.yml` (Start analyze step — mirror)

- [ ] **Step 1: Patch Start sync Python block**

After `body = json.loads(...)`, before computing polls:

```python
if body.get("reason") == "already_completed_today" or (
    body.get("started") is False and body.get("reason") == "already_completed_today"
):
    print(f"Already completed today ({body.get('date')}) — no-op success")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
        fh.write("skip_wait=true\n")
        fh.write("max_polls=0\n")
        fh.write("poll_seconds=30\n")
        fh.write("ticker_count=0\n")
    raise SystemExit(0)
```

Also handle: if `started` is False and message indicates already running, keep existing fail/continue behavior (do not treat as completed).

In Wait step, at top:

```bash
if [ "${{ steps.start.outputs.skip_wait }}" = "true" ]; then
  echo "Skipping wait — already completed today"
  exit 0
fi
```

Mirror for weekly-analysis start step (`reason` check identical).

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/daily-sync.yml .github/workflows/weekly-analysis.yml
git commit -m "$(cat <<'EOF'
No-op GitHub cron when daily run already completed.

EOF
)"
```

---

### Task 7: Frontend soft warning + force

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/components/SyncDataButton.tsx`
- Modify: `frontend/src/components/RunAnalysisButton.tsx`

- [ ] **Step 1: Types**

```typescript
export interface DailyRunSummary {
  date: string;
  timezone: string;
  status: string;
  can_resume: boolean;
  already_completed_today: boolean;
  news_done_count?: number;
  prices_done_count?: number;
  completed_count?: number;
  finished_at: string | null;
}
```

Add `daily?: DailyRunSummary` to `SyncProgress` and `AnalysisProgress`.

- [ ] **Step 2: Client**

```typescript
syncData: (tickers?: string[], opts?: { force?: boolean }) =>
  request<...>('/sync/data', {
    method: 'POST',
    body: JSON.stringify({ tickers: tickers ?? null, force: Boolean(opts?.force) }),
  }),
runAnalysis: (tickers?: string[], opts?: { force?: boolean }) =>
  request<...>('/analysis/run', {
    method: 'POST',
    body: JSON.stringify({ tickers: tickers ?? null, force: Boolean(opts?.force) }),
  }),
```

- [ ] **Step 3: SyncDataButton UI**

```tsx
const daily = statusQ.data?.daily;
const completedToday = Boolean(daily?.already_completed_today);
const canResume = Boolean(daily?.can_resume);

const label = busy
  ? 'Sync running…'
  : completedToday
    ? 'Run again'
    : 'Sync news & price data';

const subtitle = completedToday
  ? `Completed today${daily?.finished_at ? ` · ${formatHkt(daily.finished_at)}` : ''}`
  : canResume
    ? `Resuming · ${daily?.prices_done_count ?? 0} prices done`
    : null;

// onClick: mutation.mutate(completedToday)
// mutationFn: (force: boolean) => api.syncData(undefined, { force })
```

`formatHkt`: small helper — `new Date(iso).toLocaleTimeString('en-HK', { timeZone: daily.timezone || 'Asia/Hong_Kong', hour: '2-digit', minute: '2-digit' })` + ` HKT`.

Render muted `<p className="text-xs text-[var(--color-muted)]">` under the button for subtitle. No modal.

Mirror for `RunAnalysisButton` (label `Run analysis now` → `Run again`; resume subtitle uses `completed_count`).

- [ ] **Step 4: Typecheck / build if available**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors related to new props.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/components/SyncDataButton.tsx frontend/src/components/RunAnalysisButton.tsx
git commit -m "$(cat <<'EOF'
Show daily soft gate and force rerun on desk buttons.

EOF
)"
```

---

### Task 8: End-to-end verification checklist

**Files:** none (manual / local)

- [ ] **Step 1: Run full unit suite for new tests**

```bash
pytest services/tests/test_run_checkpoint_service.py services/tests/test_sync_resume.py services/tests/test_analysis_resume.py scraper/tests/test_stock_data_scraper.py -v
```

Expected: all PASS.

- [ ] **Step 2: Manual smoke (local API if DB available)**

1. Clear today’s keys in `app_settings` (`daily_sync:*`, `daily_analysis:*`) or use a throwaway DB.
2. Start sync for 2 tickers; kill process mid-prices; restart API; start sync again — logs should show only remaining prices (+ vectors).
3. After full sync, POST `/sync/data` without force → `already_completed_today`.
4. POST `/sync/data` with `{"force":true}` → starts fresh.
5. Confirm UI subtitle + Run again on Desk.

- [ ] **Step 3: Final commit only if verification fixed anything**; otherwise done.

---

## Spec coverage self-check

| Spec requirement | Task |
|------------------|------|
| HKT day boundary / `APP_TIMEZONE` | 1 |
| Checkpoint JSON in `app_settings` | 1, 3, 4 |
| Sync resume news/prices/vectors | 2, 3 |
| Price resume checkpoint-only | 3 (no bar_ts) |
| Vectors required for completed | 1, 3 |
| Analysis hybrid DB skip | 4 |
| Soft force rerun | 3, 4, 5, 7 |
| Cron no-op success | 5, 6 |
| Status `daily` payload | 3, 4, 7 |
| Integrated UI warning (no modal) | 7 |
| Rescore out of scope | 4 (untouched) |

## Placeholder / consistency notes

- Checkpoint analysis success status stored as `"completed"`; in-memory UI status may remain `"done"`.
- `is_sync_complete_for_universe` uses coverage + `vectors_done`, not solely `status` string.
- Timeouts on resume sized from todo counts, not full universe.
