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
