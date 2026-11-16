"""Weekly core directional-success card.

Reads already-materialized ``rating_outcomes`` (plus core ratings that have
not been refreshed yet) and scores direction hits. No model is involved.

One row per ticker per HKT week: the earliest core rating. The Monday weekly
job is that first write; a later forced rerun in the same week is not the
weekly baseline.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from services.run_checkpoint_service import app_timezone

DISCLAIMER = (
    "Directional experiment on weekly core ratings. "
    "A hit means the later close moved with the call. "
    "Not a performance promise."
)


def hkt_week_start(rated_at: datetime) -> date:
    """Monday of the desk calendar week (APP_TIMEZONE, default Asia/Hong_Kong)."""
    if rated_at.tzinfo is None:
        rated_at = rated_at.replace(tzinfo=timezone.utc)
    local = rated_at.astimezone(app_timezone())
    return local.date() - timedelta(days=local.weekday())


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _iso(value: datetime) -> str:
    return _as_datetime(value).isoformat()


def _is_core(row: dict[str, Any]) -> bool:
    return str(row.get("report_type") or "").strip().lower() == "core"


def _earlier(candidate: dict[str, Any], current: dict[str, Any]) -> bool:
    left = _as_datetime(candidate["rated_at"])
    right = _as_datetime(current["rated_at"])
    if left != right:
        return left < right
    return int(candidate.get("rating_id") or 0) < int(current.get("rating_id") or 0)


def canonical_weekly_core(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Earliest core rating per ticker per desk week."""
    chosen: dict[tuple[str, date], dict[str, Any]] = {}
    for row in rows:
        if not _is_core(row):
            continue
        ticker = str(row.get("ticker") or "").upper()
        if not ticker:
            continue
        week = hkt_week_start(_as_datetime(row["rated_at"]))
        key = (ticker, week)
        current = chosen.get(key)
        if current is None or _earlier(row, current):
            chosen[key] = {**row, "ticker": ticker, "_week_start": week}
    return list(chosen.values())


def _hit_summary(rows: list[dict[str, Any]], hit_key: str) -> dict[str, Any]:
    """HOLD and other unscored rows (hit is None) stay out of the denominator."""
    scored = [row for row in rows if row.get(hit_key) is not None]
    n = len(scored)
    hits = sum(1 for row in scored if row.get(hit_key) is True)
    return {
        "hit_rate": (hits / n) if n else None,
        "hits": hits,
        "n": n,
    }


def _five_day_ready(row: dict[str, Any]) -> bool:
    """Skipped rows can never gain a 5-day close, so they do not block the week."""
    if str(row.get("status") or "") == "skipped":
        return True
    return row.get("return_5d") is not None


def _outcome_label(row: dict[str, Any]) -> str:
    hit = row.get("direction_hit_5d")
    if hit is True:
        return "hit"
    if hit is False:
        return "miss"
    return "unscored"


def _week_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: str(row.get("ticker") or ""))
    out: list[dict[str, Any]] = []
    for row in ordered:
        out.append(
            {
                "ticker": row["ticker"],
                "rating": row.get("rating"),
                "score": row.get("score"),
                "rated_at": _iso(row["rated_at"]),
                "return_5d": row.get("return_5d"),
                "outcome": _outcome_label(row),
            }
        )
    return out


def _empty_week(status: str, message: str | None, pending: str | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "week_start": None,
        "week_end": None,
        "pending_week_start": pending,
        "message": message,
        "rows": [],
    }


def build_directional_success(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate core outcomes into the dashboard card payload."""
    canonical = canonical_weekly_core(rows)
    overall = {
        "5d": _hit_summary(canonical, "direction_hit_5d"),
        "20d": _hit_summary(canonical, "direction_hit_20d"),
    }
    if not canonical:
        return {
            "scope": "core",
            "disclaimer": DISCLAIMER,
            "overall": overall,
            "week": _empty_week("empty", "No weekly core ratings yet."),
        }

    by_week: dict[date, list[dict[str, Any]]] = {}
    for row in canonical:
        by_week.setdefault(row["_week_start"], []).append(row)
    weeks = sorted(by_week, reverse=True)
    latest = weeks[0]

    def pack(week: date, status: str, pending: date | None, message: str | None) -> dict[str, Any]:
        end = week + timedelta(days=6)
        return {
            "status": status,
            "week_start": week.isoformat(),
            "week_end": end.isoformat(),
            "pending_week_start": pending.isoformat() if pending else None,
            "message": message,
            "rows": _week_rows(by_week[week]),
        }

    if all(_five_day_ready(row) for row in by_week[latest]):
        return {
            "scope": "core",
            "disclaimer": DISCLAIMER,
            "overall": overall,
            "week": pack(latest, "ready", None, None),
        }

    for week in weeks[1:]:
        if all(_five_day_ready(row) for row in by_week[week]):
            message = (
                f"The latest week ({latest.isoformat()}) does not have 5-day closes yet. "
                f"Showing the previous complete week ({week.isoformat()})."
            )
            return {
                "scope": "core",
                "disclaimer": DISCLAIMER,
                "overall": overall,
                "week": pack(week, "pending_fallback", latest, message),
            }

    message = (
        f"The latest week ({latest.isoformat()}) does not have 5-day closes yet. "
        "No earlier complete week to show."
    )
    return {
        "scope": "core",
        "disclaimer": DISCLAIMER,
        "overall": overall,
        "week": _empty_week("pending", message, latest.isoformat()),
    }
