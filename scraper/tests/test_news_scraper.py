from unittest.mock import MagicMock, patch

from scraper.news_scraper import NewsScraper


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
