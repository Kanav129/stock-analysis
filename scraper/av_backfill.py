"""Choose a few equity tickers per day for the Alpha Vantage fundamentals drip.

A full statement snapshot is four requests (income, balance, cash flow, overview).
The free tier allows 25 requests a day, so the default plan is 6 tickers (24
requests) and leaves one call unused. ETFs are not company filers and are skipped.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from datetime import tzinfo
from typing import Optional

REQUESTS_PER_TICKER = 4
DEFAULT_DAILY_TICKERS = 6
DEFAULT_DAILY_REQUESTS = 24
FREE_TIER_DAILY_REQUESTS = 25

# IBKR Flex assetCategory values. ETFs share the equity universe with stocks.
STOCK_ASSET_CLASSES = frozenset({"STK", "STOCK", "STOCKS", "EQUITY", "EQUITIES"})
ETF_ASSET_CLASSES = frozenset({"ETF", "ETFS"})
ETF_QUOTE_TYPES = frozenset({"ETF", "ETN", "MUTUALFUND"})


@dataclass(frozen=True)
class BackfillCandidate:
    ticker: str
    is_etf: bool
    has_snapshot: bool
    fetched_at: Optional[datetime] = None
    checked_at: Optional[datetime] = None


@dataclass(frozen=True)
class BackfillPlan:
    selected: list[str]
    skipped_etfs: list[str]
    used_today: int
    limit: int


def is_etf(asset_class: Optional[str], quote_type: Optional[str] = None) -> bool:
    """True for ETF-classified holdings or an ETF quote type when class is unknown."""
    asset = (asset_class or "").strip().upper()
    if asset in ETF_ASSET_CLASSES:
        return True
    if asset in STOCK_ASSET_CLASSES:
        return False
    quote = (quote_type or "").strip().upper()
    return quote in ETF_QUOTE_TYPES


def needs_quote_type(asset_class: Optional[str]) -> bool:
    """Holdings already labeled stock or ETF do not need a vendor quote type."""
    asset = (asset_class or "").strip().upper()
    return asset not in STOCK_ASSET_CLASSES and asset not in ETF_ASSET_CLASSES


def daily_ticker_limit(ticker_limit: int, request_budget: int) -> int:
    """How many tickers fit in the request budget, capped under the free tier."""
    tickers = max(0, int(ticker_limit))
    budget = max(0, int(request_budget))
    budget = min(budget, FREE_TIER_DAILY_REQUESTS - 1)
    return min(tickers, budget // REQUESTS_PER_TICKER)


def configured_ticker_and_request_budget() -> tuple[int, int]:
    return (
        _env_int("AV_BACKFILL_DAILY_TICKERS", DEFAULT_DAILY_TICKERS),
        _env_int("AV_BACKFILL_DAILY_REQUESTS", DEFAULT_DAILY_REQUESTS),
    )


def plan_backfill(
    candidates: list[BackfillCandidate],
    *,
    today: date,
    limit: int,
    tz: tzinfo = timezone.utc,
) -> BackfillPlan:
    """Missing snapshots first, then the least recently checked equity.

    Names already fetched or checked on `today` count against the daily limit
    so a second run does not spend another batch of Alpha Vantage calls.
    """
    skipped = sorted({c.ticker for c in candidates if c.is_etf})
    equities = [c for c in candidates if not c.is_etf]
    used = [c for c in equities if _touched_on(c, today, tz)]
    remaining = max(0, int(limit) - len(used))
    pool = [c for c in equities if c not in used]
    pool.sort(key=lambda c: _rotation_key(c))
    selected = [c.ticker for c in pool[:remaining]]
    return BackfillPlan(
        selected=selected,
        skipped_etfs=skipped,
        used_today=len(used),
        limit=max(0, int(limit)),
    )


def _touched_on(candidate: BackfillCandidate, today: date, tz: tzinfo) -> bool:
    return _on_day(candidate.fetched_at, today, tz) or _on_day(candidate.checked_at, today, tz)


def _on_day(value: Optional[datetime], today: date, tz: tzinfo) -> bool:
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(tz).date() == today


def _rotation_key(candidate: BackfillCandidate) -> tuple:
    # Missing rows sort ahead of any saved snapshot. Among saved rows, the
    # oldest check (then fetch) is next so the universe rotates fairly.
    stamp = candidate.checked_at or candidate.fetched_at
    return (
        0 if not candidate.has_snapshot else 1,
        _as_utc(stamp) if stamp is not None else datetime.min.replace(tzinfo=timezone.utc),
        candidate.ticker,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default
