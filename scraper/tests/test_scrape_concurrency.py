"""Tests for SYNC_MAX_CONCURRENT parallel scrape paths."""
from __future__ import annotations

from unittest.mock import patch

from scraper.news_scraper import NewsScraper
from scraper.stock_data_scraper import StockDataScraper


def test_news_scrape_sequential_calls_all(monkeypatch):
    monkeypatch.setenv("SYNC_MAX_CONCURRENT", "1")
    with patch("scraper.news_scraper.MongoDBClient"):
        scraper = NewsScraper(collection_name="news", scrape_num_articles=1)
    called: list[str] = []
    done: list[str] = []

    def fake_scrape(ticker):
        called.append(ticker)

    scraper.scrape_articles = fake_scrape  # type: ignore[method-assign]
    scraper.scrape_all_tickers(
        ["AAPL", "MSFT", "NVDA"],
        on_ticker_done=lambda t: done.append(t),
    )
    assert called == ["AAPL", "MSFT", "NVDA"]
    assert done == ["AAPL", "MSFT", "NVDA"]


def test_news_scrape_parallel_processes_all(monkeypatch):
    monkeypatch.setenv("SYNC_MAX_CONCURRENT", "2")
    with patch("scraper.news_scraper.MongoDBClient"):
        scraper = NewsScraper(collection_name="news", scrape_num_articles=1)
    called: list[str] = []
    done: list[str] = []
    progress: list[tuple[str, int, int]] = []

    def fake_scrape(ticker):
        called.append(ticker)

    scraper.scrape_articles = fake_scrape  # type: ignore[method-assign]
    scraper.scrape_all_tickers(
        ["AAPL", "MSFT", "NVDA", "GOOGL"],
        on_ticker_done=lambda t: done.append(t),
        on_progress=lambda t, i, n: progress.append((t, i, n)),
    )
    assert sorted(called) == ["AAPL", "GOOGL", "MSFT", "NVDA"]
    assert sorted(done) == ["AAPL", "GOOGL", "MSFT", "NVDA"]
    assert len(progress) == 4


def test_price_scrape_parallel_processes_all(monkeypatch):
    monkeypatch.setenv("SYNC_MAX_CONCURRENT", "3")
    with patch.object(StockDataScraper, "__init__", lambda self: None):
        scraper = StockDataScraper()
    called: list[str] = []
    done: list[str] = []

    def fake_scrape(ticker, on_detail=None):
        called.append(ticker)
        return {"ticker": ticker}

    scraper.scrape_ticker = fake_scrape  # type: ignore[method-assign]
    scraper.scrape_all_tickers(
        ["AAPL", "MSFT", "NVDA"],
        on_ticker_done=lambda t: done.append(t),
    )
    assert sorted(called) == ["AAPL", "MSFT", "NVDA"]
    assert sorted(done) == ["AAPL", "MSFT", "NVDA"]
