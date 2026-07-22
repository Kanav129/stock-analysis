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
