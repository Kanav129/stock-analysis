from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd

from scraper.stock_data_scraper import StockDataScraper, _daily_bar_ts


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


def test_upsert_intraday_frame_uses_single_batch_execute():
    """Row-by-row upserts make daily sync hang on 22 tickers × ~1.7k 5m bars."""
    idx = pd.date_range("2024-01-15 14:30", periods=3, freq="5min", tz="UTC")
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
    scraper.db_client.execute_many = MagicMock(side_effect=lambda sql, rows: len(rows))

    count = scraper.upsert_intraday_frame("AAPL", frame)

    assert count == 3
    scraper.db_client.execute_many.assert_called_once()
    assert scraper.db_client.execute_query.call_count == 0
    sql, rows = scraper.db_client.execute_many.call_args.args
    assert "ON CONFLICT" in sql
    assert len(rows) == 3
    assert rows[0][0] == "AAPL"
    assert rows[0][3] == "5m"


def test_upsert_daily_frame_uses_single_batch_execute():
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
    db.execute_many.side_effect = lambda sql, rows: len(rows)
    scraper.db_client = db

    count = scraper.upsert_daily_frame("MSFT", frame)

    assert count == 2
    db.execute_many.assert_called_once()
    assert db.execute_query.call_count == 0
    _sql, rows = db.execute_many.call_args.args
    assert len(rows) == 2
    assert rows[0][0] == "MSFT"
    assert rows[0][3] == "1d"

def _sample_5m_frame() -> pd.DataFrame:
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


def test_sync_intraday_uses_5d_when_recent_bars_exist():
    """Daily cron should not re-download a full month of 5m bars every run."""
    scraper = StockDataScraper()
    scraper.db_client = MagicMock()
    scraper.db_client.fetch_query.return_value = (
        [(datetime(2024, 6, 1, 15, 0, tzinfo=timezone.utc),)],
        ["latest"],
    )
    scraper.fetch_history = MagicMock(return_value=_sample_5m_frame())
    scraper.upsert_intraday_frame = MagicMock(return_value=1)

    with patch("scraper.stock_data_scraper.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2024, 6, 2, 12, 0, tzinfo=timezone.utc)
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        scraper.sync_intraday_5m("AAPL")

    scraper.fetch_history.assert_called_once_with("AAPL", period="5d", interval="5m")


def test_sync_intraday_uses_1mo_when_no_recent_bars():
    scraper = StockDataScraper()
    scraper.db_client = MagicMock()
    scraper.db_client.fetch_query.return_value = ([], ["latest"])
    scraper.fetch_history = MagicMock(return_value=_sample_5m_frame())
    scraper.upsert_intraday_frame = MagicMock(return_value=1)

    scraper.sync_intraday_5m("AAPL")

    scraper.fetch_history.assert_called_once_with("AAPL", period="1mo", interval="5m")
