"""Finnhub API client for company news, insider transactions, and analyst data."""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from typing import Any, Optional

import requests

from utils.logger import logger


class FinnhubClient:
    """Free-tier Finnhub client (60 req/min). No API key required for basic endpoints,
    but FINNHUB_API_KEY enables the full free tier."""

    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or os.getenv("FINNHUB_API_KEY", "")
        self._last_request: float = 0.0

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-Finnhub-Token": self._api_key} if self._api_key else {}

    def _rate_limit(self) -> None:
        """Ensure at least 1 second between requests (60 req/min free tier)."""
        elapsed = time.monotonic() - self._last_request
        if elapsed < 1.05:
            time.sleep(1.05 - elapsed)
        self._last_request = time.monotonic()

    def _get(self, endpoint: str, params: Optional[dict] = None) -> Any:
        self._rate_limit()
        url = f"{self.BASE_URL}{endpoint}"
        try:
            resp = requests.get(url, headers=self._headers, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            return data if data is not None else {}
        except requests.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            # Free-tier plans often 403 premium endpoints (e.g. price-target).
            if status in (401, 403):
                logger.warning(
                    f"Finnhub {status} for {endpoint} (plan/forbidden) — skipping"
                )
                return {}
            logger.error(f"Finnhub request failed: {endpoint} — {exc}")
            return {}
        except Exception as exc:
            logger.error(f"Finnhub request failed: {endpoint} — {exc}")
            return {}

    # ── Company news ──────────────────────────────────────────────

    def get_company_news(
        self, ticker: str, from_date: Optional[str] = None, to_date: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Fetch company news.  Free tier: last 1 year, US companies only."""
        if from_date is None:
            from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        if to_date is None:
            to_date = datetime.now().strftime("%Y-%m-%d")

        params = {"symbol": ticker.upper(), "from": from_date, "to": to_date}
        result = self._get("/company-news", params)
        if isinstance(result, list):
            logger.info(f"Finnhub: {len(result)} news articles for {ticker}")
            return result
        logger.warning(f"Finnhub news returned unexpected type for {ticker}: {type(result)}")
        return []

    def get_general_news(self, category: str = "general", min_id: int = 0) -> list[dict[str, Any]]:
        """Fetch market-wide news (Finnhub /news). Free tier: general category."""
        params: dict[str, Any] = {"category": category}
        if min_id:
            params["minId"] = min_id
        result = self._get("/news", params)
        if isinstance(result, list):
            logger.info(f"Finnhub: {len(result)} general news articles ({category})")
            return result
        logger.warning(f"Finnhub general news returned unexpected type: {type(result)}")
        return []

    # ── Insider transactions ──────────────────────────────────────

    def get_insider_transactions(self, ticker: str) -> list[dict[str, Any]]:
        """Fetch insider transactions. Free tier returns latest transactions."""
        params = {"symbol": ticker.upper()}
        result = self._get("/stock/insider-transactions", params)
        data: list[dict[str, Any]] = result.get("data", []) if isinstance(result, dict) else []
        logger.info(f"Finnhub: {len(data)} insider tx for {ticker}")
        return data

    # ── Analyst recommendations ───────────────────────────────────

    def get_recommendation_trends(self, ticker: str) -> list[dict[str, Any]]:
        """Fetch analyst recommendation trends."""
        params = {"symbol": ticker.upper()}
        result = self._get("/stock/recommendation", params)
        data: list[dict[str, Any]] = result if isinstance(result, list) else []
        logger.info(f"Finnhub: {len(data)} recommendation trends for {ticker}")
        return data

    def get_price_target(self, ticker: str) -> dict[str, Any]:
        """Fetch analyst price target consensus (often premium on free tier)."""
        params = {"symbol": ticker.upper()}
        result = self._get("/stock/price-target", params)
        if not isinstance(result, dict) or not result:
            return {}
        logger.info(f"Finnhub: price target for {ticker}")
        return result

    def get_peers(self, ticker: str) -> list[str]:
        """Company peer tickers (may be empty on free tier)."""
        result = self._get("/stock/peers", {"symbol": ticker.upper()})
        if isinstance(result, list):
            return [str(p).upper() for p in result if p]
        return []

    # ── Company profile / financials ──────────────────────────────

    def get_company_profile(self, ticker: str) -> dict[str, Any]:
        """Fetch company profile (market cap, industry, etc.)."""
        params = {"symbol": ticker.upper()}
        result = self._get("/stock/profile2", params)
        return result if isinstance(result, dict) else {}

    def get_basic_financials(self, ticker: str) -> dict[str, Any]:
        """Fetch basic financial metrics (P/E, EPS, 52w range, beta, etc.)."""
        params = {"symbol": ticker.upper(), "metric": "all"}
        result = self._get("/stock/metric", params)
        metric: dict[str, Any] = result.get("metric", {}) if isinstance(result, dict) else {}
        return metric

    # ── Helpers for report sections ───────────────────────────────

    def get_insider_summary(self, ticker: str) -> dict[str, Any]:
        """Build a structured insider-activity summary for the report."""
        txns = self.get_insider_transactions(ticker)
        if not txns:
            return {"transactions": [], "total_buys": 0, "total_sells": 0, "net_shares": 0}

        recent = []
        total_buy_shares = 0
        total_sell_shares = 0

        for tx in txns[:30]:
            change = tx.get("change", 0)
            name = tx.get("name", "Unknown")
            share = abs(change)
            price = tx.get("transactionPrice", 0)
            recent.append({
                "name": name,
                "change": change,
                "shares": share,
                "price": price,
                "value": round(share * price, 2) if price else None,
                "date": tx.get("filingDate", ""),
                "code": tx.get("transactionCode", ""),
            })
            if change > 0:
                total_buy_shares += change
            else:
                total_sell_shares += abs(change)

        return {
            "transactions": recent,
            "total_buys": total_buy_shares,
            "total_sells": total_sell_shares,
            "net_shares": total_buy_shares - total_sell_shares,
            "is_net_selling": total_sell_shares > total_buy_shares,
        }

    def get_news_summary(self, ticker: str, limit: int = 15) -> list[dict[str, Any]]:
        """Get deduplicated, recent news articles for a ticker."""
        articles = self.get_company_news(ticker)
        seen = set()
        out = []
        for a in articles:
            headline = a.get("headline", "")
            if headline in seen:
                continue
            seen.add(headline)
            out.append({
                "headline": headline,
                "summary": a.get("summary", ""),
                "source": a.get("source", ""),
                "url": a.get("url", ""),
                "posted": datetime.fromtimestamp(a.get("datetime", 0)).isoformat()
                    if a.get("datetime") else None,
                "category": a.get("category", ""),
            })
            if len(out) >= limit:
                break
        return out