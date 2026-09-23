"""Alpha Vantage API client with durable statement caching for the 25 req/day free tier."""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests

from scraper.av_fundamentals_store import AvFundamentalsStore
from scraper.av_refresh import latest_fiscal_date, reported_earnings_at, should_refresh_fundamentals
from utils.logger import logger

CACHE_DIR = Path(__file__).resolve().parent.parent / ".av_cache"
CACHE_TTL_DAYS = 7
RATE_LIMIT_WINDOW = 60  # seconds for 5-call-per-minute limit


def _optional_yahoo_attr(stock: Any, name: str, ticker: str) -> Any:
    try:
        return getattr(stock, name)
    except Exception as exc:
        logger.warning("%s lookup failed for %s: %s", name, ticker, exc)
        return None


def lookup_reported_earnings(ticker: str) -> Optional[datetime]:
    """Latest earnings print from Yahoo. None when the date is unknown."""
    try:
        from scraper.yf_cache import get_yf_ticker

        stock = get_yf_ticker(ticker)
    except Exception as exc:
        logger.warning("Earnings date lookup failed for %s: %s", ticker, exc)
        return None
    # History and the calendar are separate Yahoo calls. A failure in the
    # earnings table (it needs lxml) must not discard a usable calendar date.
    frame = _optional_yahoo_attr(stock, "earnings_dates", ticker)
    calendar = _optional_yahoo_attr(stock, "calendar", ticker)
    try:
        return reported_earnings_at(frame, calendar, now=datetime.now(timezone.utc))
    except Exception as exc:
        logger.warning("Earnings date lookup failed for %s: %s", ticker, exc)
        return None


class AlphaVantageClient:
    """Free-tier AV client (25 req/day).

    Statement snapshots live in Postgres and are refreshed after a new earnings
    print. The on-disk cache only avoids repeat HTTP calls inside one fetch.
    """

    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or os.getenv("ALPHA_VANTAGE_API_KEY", "")
        self._last_request: float = 0.0
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ── Rate limiting ─────────────────────────────────────────────

    def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < 12.5:  # ~5 calls/min max (conservative for shared key)
            time.sleep(12.5 - elapsed)
        self._last_request = time.monotonic()

    # ── Caching ───────────────────────────────────────────────────

    def _cache_path(self, ticker: str, function: str) -> Path:
        return CACHE_DIR / f"{ticker.upper()}_{function}.json"

    def _read_cache(self, ticker: str, function: str) -> Optional[dict[str, Any]]:
        path = self._cache_path(ticker, function)
        if not path.exists():
            return None
        try:
            with open(path) as fh:
                data = json.load(fh)
            cached_at = data.get("_cached_at", 0)
            if cached_at and time.time() - cached_at < CACHE_TTL_DAYS * 86400:
                logger.info(f"AV cache hit: {ticker}/{function}")
                return data.get("payload")
        except Exception:
            pass
        return None

    def _write_cache(self, ticker: str, function: str, payload: dict[str, Any]) -> None:
        path = self._cache_path(ticker, function)
        try:
            with open(path, "w") as fh:
                json.dump({"_cached_at": time.time(), "payload": payload}, fh)
        except Exception as exc:
            logger.error(f"AV cache write failed: {path} — {exc}")

    # ── API ───────────────────────────────────────────────────────

    def _fetch(self, params: dict[str, str]) -> dict[str, Any]:
        self._rate_limit()
        params.setdefault("apikey", self._api_key)
        try:
            resp = requests.get(self.BASE_URL, params=params, timeout=20)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            # Detect rate limit message
            if "Note" in data or "Information" in data:
                note = data.get("Note") or data.get("Information", "")
                if "rate limit" in str(note).lower() or "thank you for using" in str(note).lower():
                    logger.warning(f"AV rate limit hit — {note}")
                    return {"_error": "rate_limit", "_message": str(note)}
            if "Error Message" in data:
                logger.warning(f"AV returned error: {data['Error Message']}")
                return {"_error": data["Error Message"]}
            return data
        except Exception as exc:
            logger.error(f"AV request failed: {params.get('function')} — {exc}")
            return {"_error": str(exc)}

    def _get_with_cache(
        self,
        ticker: str,
        function: str,
        extra_params: Optional[dict] = None,
        *,
        bypass_disk_cache: bool = False,
    ) -> dict[str, Any]:
        if not bypass_disk_cache:
            cached = self._read_cache(ticker, function)
            if cached is not None:
                return cached
        params: dict[str, str] = {"function": function, "symbol": ticker.upper()}
        if extra_params:
            params.update(extra_params)
        result = self._fetch(params)
        if not result.get("_error"):
            self._write_cache(ticker, function, result)
        return result

    # ── Public methods ────────────────────────────────────────────

    def get_income_statement(self, ticker: str) -> dict[str, Any]:
        """Annual and quarterly income statements."""
        return self._get_with_cache(ticker, "INCOME_STATEMENT")

    def get_balance_sheet(self, ticker: str) -> dict[str, Any]:
        """Annual and quarterly balance sheets."""
        return self._get_with_cache(ticker, "BALANCE_SHEET")

    def get_cash_flow(self, ticker: str) -> dict[str, Any]:
        """Annual and quarterly cash flow statements."""
        return self._get_with_cache(ticker, "CASH_FLOW")

    def get_earnings(self, ticker: str) -> dict[str, Any]:
        """Quarterly earnings (EPS estimates, actual, surprise)."""
        return self._get_with_cache(ticker, "EARNINGS")

    def get_overview(self, ticker: str) -> dict[str, Any]:
        """Company overview (market cap, P/E, EPS, beta, 52w, sector, etc.)."""
        return self._get_with_cache(ticker, "OVERVIEW")

    # ── Structured helpers for report nodes ───────────────────────

    def _safe_annual(self, data: dict[str, Any], key: str, count: int = 5) -> list[dict[str, Any]]:
        """Extract up to `count` annual reports safely."""
        reports = data.get(key, []) or data.get("annualReports", [])
        return reports[:count] if isinstance(reports, list) else []

    def _safe_quarterly(self, data: dict[str, Any], key: str, count: int = 6) -> list[dict[str, Any]]:
        reports = data.get(key, []) or data.get("quarterlyReports", [])
        return reports[:count] if isinstance(reports, list) else []

    def get_financial_snapshot(
        self,
        ticker: str,
        *,
        store: Any = None,
        now: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """Statement snapshot for the fundamentals node.

        Reuses the Postgres copy until Yahoo shows an earnings print newer than
        that save. A same-day retry is skipped when Alpha Vantage still has the
        previous fiscal period.
        """
        moment = now or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        holder = store if store is not None else AvFundamentalsStore()
        stored = _load_stored(holder, ticker)
        earnings_at = lookup_reported_earnings(ticker)
        fetched_at = stored.get("fetched_at") if stored else None
        checked_at = stored.get("checked_at") if stored else None
        if stored and not should_refresh_fundamentals(
            fetched_at=fetched_at,
            checked_at=checked_at,
            reported_earnings_at=earnings_at,
            now=moment,
        ):
            logger.info(
                "AV fundamentals reused for %s (fiscal %s)",
                ticker,
                stored.get("fiscal_date_ending"),
            )
            return stored["snapshot"]

        # Always read Alpha Vantage itself. A 7-day disk file can predate the
        # filing and would then be stamped as current.
        snapshot = self._build_snapshot(ticker, bypass_disk_cache=True)
        return _persist_refresh(holder, ticker, stored, snapshot, moment)


    def _build_snapshot(self, ticker: str, *, bypass_disk_cache: bool) -> dict[str, Any]:
        income = self._get_with_cache(ticker, "INCOME_STATEMENT", bypass_disk_cache=bypass_disk_cache)
        balance = self._get_with_cache(ticker, "BALANCE_SHEET", bypass_disk_cache=bypass_disk_cache)
        cashflow = self._get_with_cache(ticker, "CASH_FLOW", bypass_disk_cache=bypass_disk_cache)
        overview = self._get_with_cache(ticker, "OVERVIEW", bypass_disk_cache=bypass_disk_cache)
        return _assemble_snapshot(self, income, balance, cashflow, overview)


def _assemble_snapshot(
    client: AlphaVantageClient,
    income: dict[str, Any],
    balance: dict[str, Any],
    cashflow: dict[str, Any],
    overview: dict[str, Any],
) -> dict[str, Any]:
    return {
        "overview": {
            "market_cap": overview.get("MarketCapitalization"),
            "pe_ratio": overview.get("PERatio"),
            "forward_pe": overview.get("ForwardPE"),
            "peg_ratio": overview.get("PEGRatio"),
            "price_to_book": overview.get("PriceToBookRatio"),
            "eps": overview.get("EPS"),
            "beta": overview.get("Beta"),
            "sector": overview.get("Sector"),
            "industry": overview.get("Industry"),
            "week_52_high": overview.get("52WeekHigh"),
            "week_52_low": overview.get("52WeekLow"),
            "employees": overview.get("FullTimeEmployees"),
            "description": overview.get("Description"),
        },
        "income_annual": client._safe_annual(income, "annualReports"),
        "income_quarterly": client._safe_quarterly(income, "quarterlyReports"),
        "balance_annual": client._safe_annual(balance, "annualReports"),
        "balance_quarterly": client._safe_quarterly(balance, "quarterlyReports"),
        "cashflow_annual": client._safe_annual(cashflow, "annualReports"),
        "cashflow_quarterly": client._safe_quarterly(cashflow, "quarterlyReports"),
        "errors": {
            k: v.get("_error")
            for k, v in (
                ("income", income),
                ("balance", balance),
                ("cashflow", cashflow),
                ("overview", overview),
            )
            if isinstance(v, dict) and v.get("_error")
        },
    }


def _load_stored(store: Any, ticker: str) -> Optional[dict[str, Any]]:
    try:
        stored = store.load(ticker)
    except Exception as exc:
        logger.warning("AV fundamentals load failed for %s: %s", ticker, exc)
        return None
    if not stored or not isinstance(stored.get("snapshot"), dict):
        return None
    return stored


def _persist_refresh(
    store: Any,
    ticker: str,
    stored: Optional[dict[str, Any]],
    snapshot: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    new_fiscal = latest_fiscal_date(snapshot)
    old_fiscal = _coerce_date(stored.get("fiscal_date_ending")) if stored else None
    advanced = new_fiscal is not None and (old_fiscal is None or new_fiscal > old_fiscal)
    if stored and not advanced:
        logger.info(
            "AV fundamentals unchanged for %s after earnings check (fiscal %s)",
            ticker,
            old_fiscal,
        )
        _save_stored(
            store,
            ticker,
            snapshot=stored["snapshot"],
            fiscal_date_ending=old_fiscal,
            fetched_at=stored["fetched_at"],
            checked_at=now,
        )
        return stored["snapshot"]
    if new_fiscal is None:
        logger.info("AV fundamentals not stored for %s — no statement period returned", ticker)
        return snapshot
    logger.info("AV fundamentals saved for %s (fiscal %s)", ticker, new_fiscal)
    _save_stored(
        store,
        ticker,
        snapshot=snapshot,
        fiscal_date_ending=new_fiscal,
        fetched_at=now,
        checked_at=now,
    )
    return snapshot


def _save_stored(store: Any, ticker: str, **kwargs: Any) -> None:
    try:
        store.save(ticker, **kwargs)
    except Exception as exc:
        logger.warning("AV fundamentals save failed for %s: %s", ticker, exc)


def _coerce_date(value: Any) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None