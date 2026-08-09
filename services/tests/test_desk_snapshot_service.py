"""Unit tests for desk snapshot aggregation."""
from __future__ import annotations

from unittest.mock import MagicMock

from services.desk_snapshot_service import (
    MARKET_TICKERS,
    SPARK_DAYS,
    DeskSnapshotService,
)


def test_get_snapshot_batches_quotes_once():
    holdings_svc = MagicMock()
    holdings_svc.get_current_holdings.return_value = [
        {"ticker": "AAPL", "quantity": 1, "market_value": 100},
        {"ticker": "NVDA", "quantity": 2, "market_value": 200},
    ]
    holdings_svc.portfolio_summary.return_value = {
        "total_value": 300,
        "total_unrealized_pnl": 0,
        "position_count": 2,
        "snapshot_at": None,
    }
    holdings_svc.sync_metadata.return_value = {
        "holdings_synced_at": "2026-08-09T00:00:00",
        "source": "ibkr_flex",
    }

    watchlist_svc = MagicMock()
    watchlist_svc.list_items.return_value = [
        {"id": 1, "ticker": "PLTR", "notes": None, "added_at": "2026-01-01"},
        {"id": 2, "ticker": "AAPL", "notes": None, "added_at": "2026-01-02"},
    ]

    ratings_svc = MagicMock()
    ratings_svc.get_latest_ratings.return_value = [
        {"id": 1, "ticker": "AAPL", "rating": "BUY", "score": 40},
    ]
    ratings_svc.get_recent_ratings.return_value = [
        {"id": 2, "ticker": "NVDA", "rating": "HOLD", "score": 5},
    ]

    quotes_svc = MagicMock()
    quotes_svc.get_quotes.return_value = {
        "AAPL": {"ticker": "AAPL", "latest_close": 190.0, "spark": [1, 2]},
        "SPY": {"ticker": "SPY", "latest_close": 500.0, "spark": [3, 4]},
    }

    svc = DeskSnapshotService(
        holdings_service=holdings_svc,
        watchlist_service=watchlist_svc,
        ratings_service=ratings_svc,
        quotes_service=quotes_svc,
    )
    snap = svc.get_snapshot()

    assert snap["holdings"]["summary"]["position_count"] == 2
    assert snap["watchlist"]["items"][0]["ticker"] == "PLTR"
    assert snap["ratings"]["ratings"][0]["ticker"] == "AAPL"
    assert snap["recent_ratings"]["ratings"][0]["ticker"] == "NVDA"
    assert snap["quotes"]["quotes"]["AAPL"]["latest_close"] == 190.0
    assert snap["meta"]["desk_tickers"] == ["AAPL", "NVDA", "PLTR"]
    assert snap["meta"]["market_tickers"] == list(MARKET_TICKERS)
    assert snap["meta"]["spark_days"] == SPARK_DAYS

    ratings_svc.get_latest_ratings.assert_called_once_with(["AAPL", "NVDA", "PLTR"])
    expected_quotes = [*MARKET_TICKERS, "AAPL", "NVDA", "PLTR"]
    quotes_svc.get_quotes.assert_called_once_with(expected_quotes, spark_days=SPARK_DAYS)


def test_get_snapshot_empty_desk_still_returns_market_quotes():
    holdings_svc = MagicMock()
    holdings_svc.get_current_holdings.return_value = []
    holdings_svc.portfolio_summary.return_value = {
        "total_value": 0,
        "total_unrealized_pnl": 0,
        "position_count": 0,
        "snapshot_at": None,
    }
    holdings_svc.sync_metadata.return_value = {}
    watchlist_svc = MagicMock()
    watchlist_svc.list_items.return_value = []
    ratings_svc = MagicMock()
    ratings_svc.get_latest_ratings.return_value = []
    ratings_svc.get_recent_ratings.return_value = []
    quotes_svc = MagicMock()
    quotes_svc.get_quotes.return_value = {"SPY": {"ticker": "SPY", "latest_close": 1.0}}

    snap = DeskSnapshotService(
        holdings_service=holdings_svc,
        watchlist_service=watchlist_svc,
        ratings_service=ratings_svc,
        quotes_service=quotes_svc,
    ).get_snapshot()

    ratings_svc.get_latest_ratings.assert_not_called()
    quotes_svc.get_quotes.assert_called_once_with(list(MARKET_TICKERS), spark_days=SPARK_DAYS)
    assert snap["meta"]["desk_tickers"] == []
    assert "SPY" in snap["quotes"]["quotes"]
