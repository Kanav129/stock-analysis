from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd

from services.market_data_service import (
    _db_frame_is_usable,
    build_market_data,
    get_market_data,
    load_daily_bars_from_db,
)


def _sample_db_df(n: int = 220, *, end: date | None = None) -> pd.DataFrame:
    end = end or date.today()
    rows = []
    for i in range(n):
        d = end - timedelta(days=n - 1 - i)
        close = 100.0 + i * 0.1
        rows.append({
            "date": d,
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000_000 + i,
        })
    return pd.DataFrame(rows)


def test_db_frame_is_usable_when_fresh_and_enough_bars():
    df = _sample_db_df(220)
    ok, reason = _db_frame_is_usable(df)
    assert ok is True
    assert reason == "ok"


def test_db_frame_is_usable_rejects_stale():
    old_end = date.today() - timedelta(days=10)
    df = _sample_db_df(220, end=old_end)
    ok, reason = _db_frame_is_usable(df)
    assert ok is False
    assert "stale" in reason


def test_db_frame_is_usable_rejects_insufficient_bars():
    df = _sample_db_df(10)
    ok, reason = _db_frame_is_usable(df)
    assert ok is False
    assert "insufficient" in reason


def test_build_market_data_includes_sma200_and_source():
    df = _sample_db_df(220)
    out = build_market_data(df, source="stock_data")
    assert out["price_source"] == "stock_data"
    assert out["daily_bar_count"] == 220
    assert out["moving_averages"]["sma_200"] == df["close"].rolling(200).mean().iloc[-1]
    assert len(out["price_history"]) == 60


@patch("services.market_data_service.load_daily_bars_from_yfinance")
@patch("services.market_data_service.load_daily_bars_from_db")
def test_get_market_data_prefers_stock_data(mock_db, mock_yf):
    mock_db.return_value = _sample_db_df(220)
    market_data, live_price, error = get_market_data("AAPL")
    assert error is None
    assert live_price is not None
    assert market_data["price_source"] == "stock_data"
    mock_yf.assert_not_called()


@patch("services.market_data_service.load_daily_bars_from_yfinance")
@patch("services.market_data_service.load_daily_bars_from_db")
def test_get_market_data_falls_back_to_yfinance_when_db_empty(mock_db, mock_yf):
    mock_db.return_value = pd.DataFrame()
    yf_df = _sample_db_df(130)
    mock_yf.return_value = yf_df
    market_data, live_price, error = get_market_data("AAPL")
    assert error is None
    assert market_data["price_source"] == "yfinance"
    mock_yf.assert_called_once()


@patch("services.market_data_service.get_db_client")
def test_load_daily_bars_from_db_queries_1d_interval(mock_get_db):
    db = MagicMock()
    db.fetch_query.return_value = (
        [("2026-07-20", 1.0, 2.0, 0.5, 1.5, 1000)],
        ["date", "open", "high", "low", "close", "volume"],
    )
    mock_get_db.return_value = db
    df = load_daily_bars_from_db("AAPL")
    assert len(df) == 1
    sql = db.fetch_query.call_args.args[0]
    assert "bar_interval = '1d'" in sql
