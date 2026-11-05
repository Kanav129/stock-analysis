import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from scraper.news_scraper import NEWS_FETCH_TIMEOUT_SECONDS, NewsScraper, news_ticker_timeout_seconds


@patch("scraper.news_scraper.MongoDBClient")
@patch("scraper.news_scraper.yf.Ticker")
def test_scrape_articles(mock_ticker_cls, mock_mongo_cls):
    mock_mongo = mock_mongo_cls.return_value
    mock_ticker = MagicMock()
    mock_ticker.news = [
        {
            "content": {
                "title": "Test Headline",
                "summary": "Test Description",
                "pubDate": "2026-05-27T21:20:25Z",
                "provider": {"displayName": "Test Source"},
                "canonicalUrl": {"url": "https://example.com/article"},
            }
        }
    ]
    mock_ticker_cls.return_value = mock_ticker

    scraper = NewsScraper(collection_name="test_collection", scrape_num_articles=5)
    articles = scraper.scrape_articles("AAPL")

    assert len(articles) == 1
    assert articles[0]["headline"] == "Test Headline"
    assert articles[0]["source"] == "Test Source"
    assert articles[0]["description"] == "Test Description"
    assert articles[0]["ticker"] == "AAPL"
    mock_mongo.insert_many.assert_called_once()


@patch("scraper.news_scraper.MongoDBClient")
@patch.object(NewsScraper, "scrape_articles")
def test_on_ticker_done_skips_failed_news(mock_scrape, _mock_mongo):
    done: list[str] = []
    mock_scrape.side_effect = [[{"ok": True}], Exception("fail"), [{"ok": True}]]
    NewsScraper(collection_name="test_collection", scrape_num_articles=5).scrape_all_tickers(
        ["AAPL", "MSFT", "NVDA"],
        on_ticker_done=lambda t: done.append(t),
    )
    assert done == ["AAPL", "NVDA"]


def test_default_news_ticker_timeout_is_one_minute(monkeypatch):
    monkeypatch.delenv("SYNC_NEWS_TICKER_TIMEOUT_SECONDS", raising=False)
    assert NEWS_FETCH_TIMEOUT_SECONDS == 60
    assert news_ticker_timeout_seconds() == 60


@pytest.mark.parametrize("concurrency", ["1", "2"])
@patch("scraper.news_scraper.MongoDBClient")
def test_hung_ticker_news_times_out_without_fake_articles(mock_mongo_cls, monkeypatch, concurrency):
    """One stuck Yahoo news call must not block the rest of the run or insert articles."""
    monkeypatch.setenv("SYNC_MAX_CONCURRENT", concurrency)
    monkeypatch.setenv("SYNC_NEWS_TICKER_TIMEOUT_SECONDS", "0.2")
    mock_mongo = mock_mongo_cls.return_value

    class _Hang:
        @property
        def news(self):
            time.sleep(5)
            return [
                {
                    "content": {
                        "title": "Should not be stored",
                        "canonicalUrl": {"url": "https://example.com/fake"},
                    }
                }
            ]

    class _Empty:
        news: list = []

    def _ticker(symbol: str):
        return _Hang() if symbol == "VRTX" else _Empty()

    monkeypatch.setattr("scraper.news_scraper.yf.Ticker", _ticker)
    done: list[str] = []
    failed: list[tuple[str, str]] = []

    def _run() -> None:
        NewsScraper(collection_name="test_collection", scrape_num_articles=5).scrape_all_tickers(
            ["VRTX", "AAPL"],
            on_ticker_done=lambda ticker: done.append(ticker),
            on_ticker_failed=lambda ticker, exc: failed.append((ticker, type(exc).__name__)),
        )

    thread = threading.Thread(target=_run)
    thread.start()
    thread.join(3)

    assert not thread.is_alive()
    assert failed == [("VRTX", "TimeoutError")]
    assert done == ["AAPL"]
    # The hung call returns articles after we have already moved on. Those must
    # not be written — the ticker is recorded as failed, not given fake news.
    time.sleep(5.2)
    mock_mongo.insert_many.assert_not_called()


@patch("scraper.news_scraper.MongoDBClient")
@patch.object(NewsScraper, "scrape_articles")
def test_news_error_records_failure_and_continues(mock_scrape, _mock_mongo):
    done: list[str] = []
    failed: list[str] = []

    def _scrape(ticker: str):
        if ticker == "VRTX":
            raise RuntimeError("yahoo down")
        return []

    mock_scrape.side_effect = _scrape
    NewsScraper(collection_name="test_collection", scrape_num_articles=5).scrape_all_tickers(
        ["VRTX", "AAPL"],
        on_ticker_done=lambda ticker: done.append(ticker),
        on_ticker_failed=lambda ticker, exc: failed.append(ticker),
    )
    assert failed == ["VRTX"]
    assert done == ["AAPL"]
