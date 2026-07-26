from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pandas as pd

from scraper.stock_data_scraper import (
    BAR_1M,
    BAR_15M,
    StockDataScraper,
    _daily_bar_ts,
    _snap_ts,
)


@patch("scraper.stock_data_scraper.yf.Ticker")
def test_fetch_history(mock_ticker):
    mock_ticker.return_value.history.return_value = pd.DataFrame({"Close": [1.0]})
    scraper = StockDataScraper()
    data = scraper.fetch_history("AAPL", period="1mo", interval="1d")
    assert not data.empty


def test_daily_bar_ts_normalizes_to_utc_midnight():
    ts = _daily_bar_ts("2024-01-15 16:00:00-05:00")
    assert ts.hour == 0 and ts.minute == 0
    assert str(ts.date()) == "2024-01-15"


def test_snap_ts_1m_and_15m():
    ts = datetime(2024, 1, 15, 14, 31, 40, tzinfo=timezone.utc)
    assert _snap_ts(ts, BAR_1M) == datetime(2024, 1, 15, 14, 31, tzinfo=timezone.utc)
    assert _snap_ts(ts, BAR_15M) == datetime(2024, 1, 15, 14, 30, tzinfo=timezone.utc)


@patch.object(StockDataScraper, "scrape_ticker")
def test_scrape_all_tickers(mock_scrape):
    mock_scrape.return_value = {"ticker": "AAPL"}
    scraper = StockDataScraper()
    scraper.db_client = MagicMock()
    scraper.scrape_all_tickers(["AAPL", "MSFT"])
    assert mock_scrape.call_count == 2


@patch.object(StockDataScraper, "scrape_ticker")
def test_on_ticker_done_skips_failed_price(mock_scrape):
    done: list[str] = []
    mock_scrape.side_effect = [{"ok": True}, Exception("fail"), {"ok": True}]
    StockDataScraper().scrape_all_tickers(
        ["AAPL", "MSFT", "NVDA"],
        on_ticker_done=lambda t: done.append(t),
    )
    assert done == ["AAPL", "NVDA"]


def test_upsert_interval_frame_uses_execute_values():
    idx = pd.date_range("2024-01-15 14:30", periods=3, freq="1min", tz="UTC")
    frame = pd.DataFrame(
        {
            "Open": [1.0, 2.0, 3.0],
            "High": [1.1, 2.1, 3.1],
            "Low": [0.9, 1.9, 2.9],
            "Close": [1.05, 2.05, 3.05],
            "Volume": [100, 200, 300],
        },
        index=idx,
    )
    scraper = StockDataScraper()
    scraper.db_client = MagicMock()
    scraper.db_client.execute_values = MagicMock(side_effect=lambda sql, rows, **kw: len(rows))

    count = scraper.upsert_interval_frame("AAPL", frame, BAR_1M)

    assert count == 3
    scraper.db_client.execute_values.assert_called_once()
    scraper.db_client.execute_many.assert_not_called()
    sql, rows = scraper.db_client.execute_values.call_args.args
    assert "ON CONFLICT" in sql
    assert "VALUES %s" in sql
    assert len(rows) == 3
    assert rows[0][0] == "AAPL"
    assert rows[0][3] == "1m"


def test_upsert_daily_frame_uses_execute_values():
    idx = pd.to_datetime(["2024-01-15", "2024-01-16"], utc=True)
    frame = pd.DataFrame(
        {
            "Open": [10.0, 11.0],
            "High": [10.5, 11.5],
            "Low": [9.5, 10.5],
            "Close": [10.2, 11.2],
            "Volume": [1000, 1100],
        },
        index=idx,
    )
    scraper = StockDataScraper()
    db = MagicMock()
    db.execute_values.side_effect = lambda sql, rows, **kw: len(rows)
    scraper.db_client = db

    count = scraper.upsert_daily_frame("MSFT", frame)

    assert count == 2
    db.execute_values.assert_called_once()
    db.execute_many.assert_not_called()
    _sql, rows = db.execute_values.call_args.args
    assert len(rows) == 2
    assert rows[0][0] == "MSFT"
    assert rows[0][3] == "1d"


def _sample_1m_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [1.0],
            "High": [1.0],
            "Low": [1.0],
            "Close": [1.0],
            "Volume": [1],
        },
        index=pd.DatetimeIndex([pd.Timestamp("2024-01-15 14:30", tz="UTC")]),
    )


def test_sync_band_delta_fetches_from_latest_minus_overlap():
    scraper = StockDataScraper()
    scraper.db_client = MagicMock()
    recent = datetime.now(timezone.utc) - timedelta(hours=1)
    scraper.db_client.fetch_query.return_value = ([(recent,)], ["latest"])
    scraper.fetch_history = MagicMock(return_value=_sample_1m_frame())
    scraper.upsert_interval_frame = MagicMock(return_value=1)

    scraper.sync_band("AAPL", BAR_1M)

    scraper.fetch_history.assert_called_once()
    kwargs = scraper.fetch_history.call_args.kwargs
    assert kwargs["interval"] == "1m"
    assert "period" not in kwargs
    assert kwargs["start"] == recent - timedelta(hours=2)


def test_sync_band_backfills_long_period_when_no_bars():
    scraper = StockDataScraper()
    scraper.db_client = MagicMock()
    scraper.db_client.fetch_query.return_value = ([], ["latest"])
    scraper.fetch_history = MagicMock(return_value=_sample_1m_frame())
    scraper.upsert_interval_frame = MagicMock(return_value=1)

    scraper.sync_band("AAPL", BAR_1M)

    scraper.fetch_history.assert_called_once_with("AAPL", period="7d", interval="1m")


def test_sync_band_skips_when_latest_is_very_fresh():
    scraper = StockDataScraper()
    scraper.db_client = MagicMock()
    recent = datetime.now(timezone.utc) - timedelta(minutes=1)
    scraper.db_client.fetch_query.return_value = ([(recent,)], ["latest"])
    scraper.fetch_history = MagicMock()
    scraper.upsert_interval_frame = MagicMock()

    n = scraper.sync_band("AAPL", BAR_1M)

    assert n == 0
    scraper.fetch_history.assert_not_called()
    scraper.upsert_interval_frame.assert_not_called()


def test_refresh_live_1m_uses_delta_when_recent_1m_exists():
    scraper = StockDataScraper()
    scraper.db_client = MagicMock()
    recent = datetime.now(timezone.utc) - timedelta(minutes=10)
    scraper.db_client.fetch_query.return_value = ([(recent,)], ["latest"])
    scraper.fetch_history = MagicMock(return_value=_sample_1m_frame())
    scraper.upsert_interval_frame = MagicMock(return_value=1)

    assert scraper.refresh_live_1m("aapl") == 1
    kwargs = scraper.fetch_history.call_args.kwargs
    assert kwargs["interval"] == "1m"
    assert kwargs["start"] == recent - timedelta(hours=2)
    assert "period" not in kwargs


def test_chart_interval_mapping():
    from rest_api.routes.stock_routes import _chart_interval_for_duration

    assert _chart_interval_for_duration(1) == "1m"
    assert _chart_interval_for_duration(7) == "15m"
    assert _chart_interval_for_duration(14) == "30m"
    assert _chart_interval_for_duration(30) == "1h"
    assert _chart_interval_for_duration(90) == "1d"
    assert _chart_interval_for_duration(None) == "1d"


def test_fetch_last_us_session_queries_ny_date():
    from rest_api.routes.stock_routes import _fetch_last_us_session

    db = MagicMock()
    db.fetch_query.return_value = ([], [])
    _fetch_last_us_session(db, "AAPL", "1m", "close")
    sql, params = db.fetch_query.call_args.args
    assert "America/New_York" in sql
    assert params == ("AAPL", "1m", "AAPL", "1m")


def test_refresh_live_1m_uses_1d_then_2d_fallback_when_no_local_bars():
    scraper = StockDataScraper()
    scraper.db_client = MagicMock()
    scraper.db_client.fetch_query.return_value = ([], ["latest"])
    scraper.fetch_history = MagicMock(side_effect=[pd.DataFrame(), _sample_1m_frame()])
    scraper.upsert_interval_frame = MagicMock(return_value=1)

    assert scraper.refresh_live_1m("aapl") == 1
    calls = scraper.fetch_history.call_args_list
    assert calls[0].args == ("AAPL",)
    assert calls[0].kwargs == {"period": "1d", "interval": "1m"}
    assert calls[1].kwargs == {"period": "2d", "interval": "1m"}
    scraper.upsert_interval_frame.assert_called_once()


def test_refresh_live_1m_skips_fallback_when_1d_has_data():
    scraper = StockDataScraper()
    scraper.db_client = MagicMock()
    scraper.db_client.fetch_query.return_value = ([], ["latest"])
    scraper.fetch_history = MagicMock(return_value=_sample_1m_frame())
    scraper.upsert_interval_frame = MagicMock(return_value=3)

    assert scraper.refresh_live_1m("MSFT") == 3
    scraper.fetch_history.assert_called_once_with("MSFT", period="1d", interval="1m")


@patch("rest_api.routes.stock_routes.sync_service")
def test_live_price_refresh_skips_when_sync_running(mock_sync):
    from rest_api.routes.stock_routes import live_price_refresh
    from rest_api.schemas import LivePriceRefreshRequest

    mock_sync.is_running.return_value = True
    out = live_price_refresh(LivePriceRefreshRequest(tickers=["AAPL"]))
    assert out["skipped"] is True
    assert out["reason"] == "sync_running"
