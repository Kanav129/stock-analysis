"""Desk bootstrap aggregate: holdings + watchlist + ratings + quotes in one call."""
from __future__ import annotations

from typing import Any

from services.holdings_service import HoldingsService
from services.quotes_service import QuotesService
from services.ratings_service import RatingsService
from services.watchlist_service import WatchlistService

MARKET_TICKERS = ["SPY", "QQQ", "IWM", "DIA"]
SPARK_DAYS = 7
RECENT_RATINGS_LIMIT = 7
MAX_QUOTE_TICKERS = 80


class DeskSnapshotService:
    def __init__(
        self,
        *,
        holdings_service: HoldingsService | None = None,
        watchlist_service: WatchlistService | None = None,
        ratings_service: RatingsService | None = None,
        quotes_service: QuotesService | None = None,
    ) -> None:
        self._holdings = holdings_service or HoldingsService()
        self._watchlist = watchlist_service or WatchlistService()
        self._ratings = ratings_service or RatingsService()
        self._quotes = quotes_service or QuotesService()

    def get_snapshot(self) -> dict[str, Any]:
        holdings = self._holdings.get_current_holdings()
        summary = self._holdings.portfolio_summary()
        meta = self._holdings.sync_metadata()
        watch_items = self._watchlist.list_items()

        holdings_tickers = [
            str(h.get("ticker", "")).strip().upper()
            for h in holdings
            if h.get("ticker")
        ]
        watch_tickers = [
            str(i.get("ticker", "")).strip().upper()
            for i in watch_items
            if i.get("ticker")
        ]
        desk_tickers = sorted(set(holdings_tickers) | set(watch_tickers))

        ratings = (
            self._ratings.get_latest_ratings(desk_tickers) if desk_tickers else []
        )
        recent_ratings = self._ratings.get_recent_ratings(RECENT_RATINGS_LIMIT)

        quote_tickers = self._quote_tickers(desk_tickers)
        quotes = (
            self._quotes.get_quotes(quote_tickers, spark_days=SPARK_DAYS)
            if quote_tickers
            else {}
        )

        return {
            "holdings": {
                "holdings": holdings,
                "summary": summary,
                "holdings_synced_at": meta.get("holdings_synced_at"),
                "source": meta.get("source"),
            },
            "watchlist": {"items": watch_items},
            "ratings": {"ratings": ratings},
            "recent_ratings": {"ratings": recent_ratings},
            "quotes": {"quotes": quotes},
            "meta": {
                "desk_tickers": desk_tickers,
                "market_tickers": list(MARKET_TICKERS),
                "spark_days": SPARK_DAYS,
                "recent_limit": RECENT_RATINGS_LIMIT,
            },
        }

    @staticmethod
    def _quote_tickers(desk_tickers: list[str]) -> list[str]:
        """Market indices first, then desk tickers — capped for QuotesService safety."""
        seen: set[str] = set()
        out: list[str] = []
        for t in [*MARKET_TICKERS, *desk_tickers]:
            if not t or t in seen:
                continue
            seen.add(t)
            out.append(t)
            if len(out) >= MAX_QUOTE_TICKERS:
                break
        return out


desk_snapshot_service = DeskSnapshotService()
