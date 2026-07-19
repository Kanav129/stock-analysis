"""Social sentiment scraper — StockTwits public API + Reddit read-only .json endpoints.
Free, no authentication required. Aggressively rate-limited to avoid blocks."""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

import requests

from utils.logger import logger


class SocialScraper:
    """Fetches social sentiment data from StockTwits and Reddit."""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "stocks-insights-agent/1.0 (personal research; contact@example.com)"
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
            return resp.json()  # type: ignore[no-any-return]
        except Exception as exc:
            logger.error(f"Social scrape failed: {url} — {exc}")
            return {}

    # ── StockTwits ────────────────────────────────────────────────

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

    # ── Reddit ────────────────────────────────────────────────────

    REDDIT_SUBREDDITS = ["wallstreetbets", "stocks", "investing"]

    def get_reddit_posts(self, ticker: str, days: int = 7, limit: int = 20) -> list[dict[str, Any]]:
        """Search Reddit for ticker mentions across finance subreddits.
        Uses read-only .json endpoints — no auth required."""
        after = (datetime.utcnow() - timedelta(days=days)).timestamp()
        posts: list[dict[str, Any]] = []
        for sub in self.REDDIT_SUBREDDITS:
            url = f"https://www.reddit.com/r/{sub}/search.json"
            params = {"q": ticker.upper(), "sort": "new", "limit": min(limit, 25), "restrict_sr": "on"}
            data = self._get_json(url, params)
            children = data.get("data", {}).get("children", []) if isinstance(data, dict) else []
            for child in children:
                post_data = child.get("data", {})
                created = post_data.get("created_utc", 0)
                if created < after:
                    continue
                posts.append({
                    "id": post_data.get("id"),
                    "title": post_data.get("title", ""),
                    "selftext": post_data.get("selftext", "")[:500],
                    "subreddit": sub,
                    "score": post_data.get("score", 0),
                    "num_comments": post_data.get("num_comments", 0),
                    "created_utc": created,
                    "url": f"https://www.reddit.com{post_data.get('permalink', '')}",
                    "flair": post_data.get("link_flair_text", ""),
                })
            if len(posts) >= limit:
                posts = posts[:limit]
                break
            time.sleep(1.5)  # be kind to Reddit's servers

        logger.info(f"Reddit: {len(posts)} posts for {ticker}")
        return posts[:limit]

    # ── Combined summary ──────────────────────────────────────────

    def get_sentiment_summary(self, ticker: str) -> dict[str, Any]:
        """Combined StockTwits + Reddit sentiment for the report."""
        st = self.get_stocktwits_sentiment(ticker)
        reddit = self.get_reddit_posts(ticker)

        # Simple Reddit aggregate
        reddit_total = len(reddit)
        reddit_avg_score = round(sum(p["score"] for p in reddit) / max(reddit_total, 1), 1)
        reddit_avg_comments = round(sum(p["num_comments"] for p in reddit) / max(reddit_total, 1), 1)

        return {
            "stocktwits": st,
            "reddit": {
                "total_posts": reddit_total,
                "average_score": reddit_avg_score,
                "average_comments": reddit_avg_comments,
                "sample": reddit[:10],
                "has_engagement": reddit_total > 0,
            },
            "cross_source_alignment": self._alignment(st, reddit),
        }

    @staticmethod
    def _alignment(
        st: dict[str, Any], reddit: list[dict[str, Any]]
    ) -> str:
        """Simple heuristic alignment check between sources."""
        st_bullish = st.get("bullish_pct", 0) > 50
        reddit_busy = len(reddit) > 5
        if st_bullish and reddit_busy:
            return "positive_alignment"
        if not st_bullish and reddit_busy:
            return "conflicting"
        if st.get("total", 0) == 0 and len(reddit) == 0:
            return "no_data"
        return "mixed"