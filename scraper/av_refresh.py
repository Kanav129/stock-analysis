"""Decide when a saved Alpha Vantage fundamentals snapshot is still current."""
from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Any, Optional

_STATEMENT_KEYS = (
    "income_quarterly",
    "income_annual",
    "balance_quarterly",
    "balance_annual",
    "cashflow_quarterly",
    "cashflow_annual",
)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def should_refresh_fundamentals(
    *,
    fetched_at: Optional[datetime],
    checked_at: Optional[datetime],
    reported_earnings_at: Optional[datetime],
    now: datetime,
) -> bool:
    """Refresh only for a missing snapshot or a print we have not already checked today.

    Price-derived multiples come from Yahoo on every run. Statement rows stay the
    same until the company files, so a weekly pass reuses the saved snapshot.
    """
    if fetched_at is None:
        return True
    if reported_earnings_at is None:
        return False
    earnings = _as_utc(reported_earnings_at)
    if earnings <= _as_utc(fetched_at):
        return False
    if checked_at is not None:
        checked = _as_utc(checked_at)
        if checked >= earnings and checked.date() == _as_utc(now).date():
            return False
    return True


def latest_fiscal_date(snapshot: dict[str, Any] | None) -> Optional[date]:
    """Newest fiscal period present in the saved statement rows."""
    if not snapshot:
        return None
    found: list[date] = []
    for key in _STATEMENT_KEYS:
        rows = snapshot.get(key) or []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            parsed = _parse_date(row.get("fiscalDateEnding") or row.get("fiscal_date_ending"))
            if parsed is not None:
                found.append(parsed)
    return max(found) if found else None


def reported_earnings_at(
    frame: Any,
    calendar: Any,
    *,
    now: datetime,
) -> Optional[datetime]:
    """Latest earnings print that has already happened.

    Future estimate rows and a still-upcoming calendar date are ignored.
    """
    from_history = _from_earnings_frame(frame)
    if from_history is not None:
        return from_history
    return _from_calendar(calendar, now=_as_utc(now))


def _from_earnings_frame(frame: Any) -> Optional[datetime]:
    if frame is None:
        return None
    try:
        reported = frame["Reported EPS"]
        index = list(frame.index)
    except (KeyError, TypeError, AttributeError):
        return None
    found: list[datetime] = []
    for raw_ts, actual in zip(index, list(reported)):
        if not _has_reported_actual(actual):
            continue
        parsed = _parse_datetime(raw_ts)
        if parsed is not None:
            found.append(parsed)
    return max(found) if found else None


def _from_calendar(calendar: Any, *, now: datetime) -> Optional[datetime]:
    raw_dates = _calendar_values(calendar)
    found: list[datetime] = []
    for raw in raw_dates:
        parsed = _parse_datetime(raw)
        if parsed is not None and parsed <= now:
            found.append(parsed)
    return max(found) if found else None


def _calendar_values(calendar: Any) -> list[Any]:
    if calendar is None:
        return []
    if isinstance(calendar, dict):
        raw = calendar.get("Earnings Date")
        if raw is None:
            raw = calendar.get("earningsDate")
        if raw is None:
            return []
        if isinstance(raw, (list, tuple)):
            return list(raw)
        return [raw]
    try:
        import pandas as pd
    except ImportError:
        pd = None  # type: ignore
    if pd is not None and isinstance(calendar, pd.DataFrame) and not calendar.empty:
        row = calendar.iloc[0]
        for key in ("Earnings Date", "earningsDate"):
            if key in calendar.columns:
                raw = row[key]
                if isinstance(raw, (list, tuple)):
                    return list(raw)
                return [raw]
    return []


def _has_reported_actual(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    text = str(value).strip().lower()
    return text not in {"", "nan", "none", "<na>", "nat"}


def _parse_date(raw: Any) -> Optional[date]:
    parsed = _parse_datetime(raw)
    if parsed is None:
        return None
    return parsed.date()


def _parse_datetime(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return _as_utc(raw)
    if isinstance(raw, date):
        return datetime(raw.year, raw.month, raw.day, tzinfo=timezone.utc)
    text = str(raw).strip()
    if not text or text.lower() in {"nan", "none", "nat"}:
        return None
    if "T" in text or " " in text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
    try:
        day = date.fromisoformat(text[:10])
    except ValueError:
        return None
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
