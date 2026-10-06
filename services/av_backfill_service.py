"""Daily Alpha Vantage drip into av_fundamentals.

This does not schedule itself. POST /cron/av-backfill runs one batch. The
GitHub workflow that calls it is manual until a daily schedule is approved.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from datetime import tzinfo
from typing import Any, Callable, Optional

from scraper.alpha_vantage_scraper import AlphaVantageClient
from scraper.av_backfill import (
    FREE_TIER_DAILY_REQUESTS,
    REQUESTS_PER_TICKER,
    BackfillCandidate,
    configured_ticker_and_request_budget,
    daily_ticker_limit,
    is_etf,
    needs_quote_type,
    plan_backfill,
)
from scraper.av_fundamentals_store import AvFundamentalsStore
from services.holdings_service import HoldingsService
from services.run_checkpoint_service import app_timezone
from services.universe_service import UniverseService
from utils.logger import logger

QuoteLookup = Callable[[str], Optional[str]]


def _yahoo_quote_type(ticker: str) -> Optional[str]:
    try:
        from scraper.yf_cache import get_yf_ticker

        info = getattr(get_yf_ticker(ticker), "info", None) or {}
        if not isinstance(info, dict):
            return None
        raw = info.get("quoteType")
        return str(raw) if raw else None
    except Exception as exc:
        logger.warning("Quote type lookup failed for %s (%s)", ticker, type(exc).__name__)
        return None


class AvBackfillService:
    def __init__(
        self,
        *,
        universe: Any = None,
        holdings: Any = None,
        store: Any = None,
        client: Any = None,
        quote_types: Optional[dict[str, Optional[str]]] = None,
        quote_type_lookup: Optional[QuoteLookup] = None,
        tz: Optional[tzinfo] = None,
        daily_tickers: Optional[int] = None,
        daily_requests: Optional[int] = None,
    ) -> None:
        self.universe = universe if universe is not None else UniverseService()
        self.holdings = holdings if holdings is not None else HoldingsService()
        self.store = store if store is not None else AvFundamentalsStore()
        self._client = client
        self._quote_types = quote_types
        self._quote_type_lookup = quote_type_lookup
        self._tz = tz
        self._daily_tickers = daily_tickers
        self._daily_requests = daily_requests

    def run(
        self,
        *,
        dry_run: bool = False,
        now: Optional[datetime] = None,
    ) -> dict[str, Any]:
        moment = now or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        zone = self._tz or app_timezone()
        today = moment.astimezone(zone).date()
        ticker_setting, request_setting = self._limits()
        limit = daily_ticker_limit(ticker_setting, request_setting)
        request_budget = min(max(request_setting, 0), FREE_TIER_DAILY_REQUESTS - 1)

        try:
            candidates = self._candidates()
        except Exception as exc:
            logger.warning("AV backfill could not load candidates (%s)", type(exc).__name__)
            return self._empty(
                dry_run=dry_run,
                limit=limit,
                request_budget=request_budget,
                reason="candidates_unavailable",
            )

        plan = plan_backfill(candidates, today=today, limit=limit, tz=zone)
        payload: dict[str, Any] = {
            "dry_run": dry_run,
            "limit": plan.limit,
            "requests_per_ticker": REQUESTS_PER_TICKER,
            "request_budget": request_budget,
            "used_today": plan.used_today,
            "skipped_etfs": plan.skipped_etfs,
            "selected": plan.selected,
            "refreshed": [],
            "reused": [],
            "errors": [],
            "requests_made": 0,
            "reason": _idle_reason(plan.selected, plan.used_today, plan.limit),
        }
        logger.info(
            "AV backfill selected %s (dry_run=%s, skipped_etfs=%s)",
            plan.selected,
            dry_run,
            plan.skipped_etfs,
        )
        if dry_run or not plan.selected:
            return payload
        if self._client is None and not os.getenv("ALPHA_VANTAGE_API_KEY", "").strip():
            payload["reason"] = "missing_api_key"
            return payload

        client = self._client if self._client is not None else AlphaVantageClient()
        refreshed: list[str] = []
        reused: list[str] = []
        errors: list[dict[str, str]] = []
        spent = 0
        for ticker in plan.selected:
            if spent + REQUESTS_PER_TICKER > request_budget:
                break
            before = int(getattr(client, "requests_made", 0) or 0)
            try:
                snapshot = client.get_financial_snapshot(
                    ticker,
                    store=self.store,
                    now=moment,
                    refresh=True,
                    mark_checked=True,
                )
            except Exception as exc:
                logger.warning("AV backfill failed for %s (%s)", ticker, type(exc).__name__)
                errors.append({"ticker": ticker, "error": "request_failed"})
                continue
            used = int(getattr(client, "requests_made", 0) or 0) - before
            spent += max(0, used)
            if _hit_rate_limit(client, snapshot):
                errors.append({"ticker": ticker, "error": "rate_limit"})
                break
            public_error = _public_error(snapshot)
            if public_error:
                errors.append({"ticker": ticker, "error": public_error})
            elif used:
                refreshed.append(ticker)
            else:
                reused.append(ticker)
        payload["refreshed"] = refreshed
        payload["reused"] = reused
        payload["errors"] = errors
        payload["requests_made"] = spent
        if payload["reason"] is None and errors and not refreshed and not reused:
            payload["reason"] = "request_failed"
        return payload

    def _limits(self) -> tuple[int, int]:
        configured_tickers, configured_requests = configured_ticker_and_request_budget()
        tickers = configured_tickers if self._daily_tickers is None else self._daily_tickers
        requests = configured_requests if self._daily_requests is None else self._daily_requests
        return tickers, requests

    def _candidates(self) -> list[BackfillCandidate]:
        tickers = sorted({str(t).strip().upper() for t in self.universe.get_tickers() if str(t).strip()})
        assets = {
            str(symbol).strip().upper(): value
            for symbol, value in (self.holdings.current_asset_classes() or {}).items()
            if str(symbol).strip()
        }
        status = {
            str(row.get("ticker") or "").strip().upper(): row
            for row in self.store.list_status()
            if str(row.get("ticker") or "").strip()
        }
        candidates: list[BackfillCandidate] = []
        for ticker in tickers:
            asset = assets.get(ticker)
            quote = self._quote_type_for(ticker) if needs_quote_type(asset) else None
            row = status.get(ticker) or {}
            candidates.append(
                BackfillCandidate(
                    ticker=ticker,
                    is_etf=is_etf(asset, quote),
                    has_snapshot=bool(row),
                    fetched_at=row.get("fetched_at"),
                    checked_at=row.get("checked_at"),
                )
            )
        return candidates

    def _quote_type_for(self, ticker: str) -> Optional[str]:
        if self._quote_types is not None:
            return self._quote_types.get(ticker)
        if self._quote_type_lookup is not None:
            return self._quote_type_lookup(ticker)
        return _yahoo_quote_type(ticker)

    def _empty(
        self,
        *,
        dry_run: bool,
        limit: int,
        request_budget: int,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "dry_run": dry_run,
            "limit": limit,
            "requests_per_ticker": REQUESTS_PER_TICKER,
            "request_budget": request_budget,
            "used_today": 0,
            "skipped_etfs": [],
            "selected": [],
            "refreshed": [],
            "reused": [],
            "errors": [],
            "requests_made": 0,
            "reason": reason,
        }


def _idle_reason(selected: list[str], used_today: int, limit: int) -> Optional[str]:
    if selected:
        return None
    if limit > 0 and used_today >= limit:
        return "daily_limit_reached"
    return "nothing_to_refresh"


def _hit_rate_limit(client: Any, snapshot: Any) -> bool:
    if getattr(client, "rate_limited", False):
        return True
    errors = snapshot.get("errors") if isinstance(snapshot, dict) else None
    return isinstance(errors, dict) and any(value == "rate_limit" for value in errors.values())


def _public_error(snapshot: Any) -> Optional[str]:
    """Stable error code. Alpha Vantage messages can echo the request URL."""
    if not isinstance(snapshot, dict):
        return "request_failed"
    errors = snapshot.get("errors")
    if not isinstance(errors, dict) or not errors:
        return None
    if any(value == "rate_limit" for value in errors.values()):
        return "rate_limit"
    return "request_failed"


av_backfill_service = AvBackfillService()
