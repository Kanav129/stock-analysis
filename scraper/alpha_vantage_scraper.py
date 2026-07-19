"""Alpha Vantage API client with aggressive caching for the 25 req/day free tier."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import requests

from utils.logger import logger

CACHE_DIR = Path(__file__).resolve().parent.parent / ".av_cache"
CACHE_TTL_DAYS = 7
RATE_LIMIT_WINDOW = 60  # seconds for 5-call-per-minute limit


class AlphaVantageClient:
    """Free-tier AV client (25 req/day). Results are cached to disk for 7 days.
    Reports reuse cached data; only regenerated reports with expired cache trigger new calls."""

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

    def _get_with_cache(self, ticker: str, function: str, extra_params: Optional[dict] = None) -> dict[str, Any]:
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

    def get_financial_snapshot(self, ticker: str) -> dict[str, Any]:
        """Return a structured financial snapshot for the fundamentals report node.
        Cached for 7 days; re-fetches only when cache expires."""
        income = self.get_income_statement(ticker)
        balance = self.get_balance_sheet(ticker)
        cashflow = self.get_cash_flow(ticker)
        overview = self.get_overview(ticker)

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
            "income_annual": self._safe_annual(income, "annualReports"),
            "income_quarterly": self._safe_quarterly(income, "quarterlyReports"),
            "balance_annual": self._safe_annual(balance, "annualReports"),
            "balance_quarterly": self._safe_quarterly(balance, "quarterlyReports"),
            "cashflow_annual": self._safe_annual(cashflow, "annualReports"),
            "cashflow_quarterly": self._safe_quarterly(cashflow, "quarterlyReports"),
            "errors": {
                k: v.get("_error") for k, v in [
                    ("income", income), ("balance", balance),
                    ("cashflow", cashflow), ("overview", overview),
                ] if v.get("_error")
            },
        }