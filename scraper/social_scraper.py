"""Social sentiment scraper — StockTwits public API.

Reddit was removed: free/anonymous access is blocked and paid API is out of scope.
"""
from __future__ import annotations

import time
from typing import Any

import requests

from utils.logger import logger


class SocialScraper:
    """Fetches social sentiment data from StockTwits."""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "stocks-insights-agent/1.0 (personal research)"
        })
        self._last_request: float = 0.0

    def _rate_limit(self, min_gap: float = 1.0) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < min_gap:
            time.sleep(min_gap - elapsed)
        self._last_request = time.monotonic()

    def _get_json(self, url: str, params: dict | None = None, timeout: int = 15) -> dict[str, Any]:
        self._rate_limit()
        try:
            resp = self._session.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.error(f"Social scrape failed: {url} — {exc}")
            return {}

    def get_stocktwits_messages(self, ticker: str, limit: int = 30) -> list[dict[str, Any]]:
        """Fetch recent StockTwits messages for a ticker.
        Public API endpoint — no auth required."""
        url = f"https://api.stocktwits.com/api/2/streams/symbol/{ticker.upper()}.json"
        data = self._get_json(url)
        messages: list[dict[str, Any]] = data.get("messages", []) if isinstance(data, dict) else []
        parsed = []
        for msg in messages[:limit]:
            entities = msg.get("entities", {}).get("sentiment", {})
            parsed.append({
                "id": msg.get("id"),
                "body": msg.get("body", ""),
                "created_at": msg.get("created_at", ""),
                "sentiment": entities.get("basic") if entities else None,
                "user": (msg.get("user") or {}).get("username", ""),
                "likes": msg.get("likes", {}).get("total", 0) if msg.get("likes") else 0,
            })
        logger.info(f"StockTwits: {len(parsed)} messages for {ticker}")
        return parsed

    def get_stocktwits_sentiment(self, ticker: str, limit: int = 30) -> dict[str, Any]:
        """Compute a sentiment summary from recent StockTwits messages."""
        msgs = self.get_stocktwits_messages(ticker, limit)
        bullish = sum(1 for m in msgs if m.get("sentiment") == "Bullish")
        bearish = sum(1 for m in msgs if m.get("sentiment") == "Bearish")
        total = len(msgs)
        ratio = bullish / max(bearish, 1)
        return {
            "total": total,
            "bullish": bullish,
            "bearish": bearish,
            "bullish_pct": round(bullish / max(total, 1) * 100, 1),
            "bearish_pct": round(bearish / max(total, 1) * 100, 1),
            "bull_bear_ratio": round(ratio, 2) if bearish else None,
            "is_strongly_bullish": bullish > 0 and bearish == 0,
            "sample": msgs[:10],
            "source": "StockTwits",
        }

    def get_sentiment_summary(self, ticker: str) -> dict[str, Any]:
        """StockTwits sentiment summary for the research report."""
        st = self.get_stocktwits_sentiment(ticker)
        return {
            "stocktwits": st,
            "cross_source_alignment": self._alignment(st),
        }

    @staticmethod
    def _alignment(st: dict[str, Any]) -> str:
        """Simple heuristic from StockTwits alone."""
        if st.get("total", 0) == 0:
            return "no_data"
        if st.get("bullish_pct", 0) > 60:
            return "positive"
        if st.get("bearish_pct", 0) > 60:
            return "negative"
        return "mixed"
