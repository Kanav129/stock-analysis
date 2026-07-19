import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import yfinance as yf
from dotenv import load_dotenv

from db.mongo_db import MongoDBClient
from scraper.generic_scraper import GenericScraper
from utils.logger import logger


class NewsScraper(GenericScraper):
    def __init__(self, collection_name, scrape_num_articles=1):
        self.collection_name = collection_name
        self.scrape_num_articles = scrape_num_articles
        self.mongo_client = MongoDBClient()

    @staticmethod
    def _parse_yfinance_item(item: Dict[str, Any], ticker: str) -> Optional[Dict[str, Any]]:
        content = item.get("content") or item
        title = (content.get("title") or "").strip()
        if not title:
            return None

        summary = (content.get("summary") or content.get("description") or "").strip()
        provider = content.get("provider")
        source = provider.get("displayName") if isinstance(provider, dict) else (provider or "Yahoo Finance")

        canonical = content.get("canonicalUrl")
        link = canonical.get("url") if isinstance(canonical, dict) else (content.get("link") or "")

        pub_date = content.get("pubDate") or content.get("displayTime") or ""
        posted = pub_date
        if pub_date:
            try:
                posted = datetime.fromisoformat(pub_date.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
            except ValueError:
                posted = pub_date

        return {
            "ticker": ticker.upper(),
            "headline": title,
            "source": source,
            "posted": posted,
            "description": summary or title,
            "link": link,
            "synced": False,
        }

    def scrape_articles(self, search_query: str) -> List[Dict[str, Any]]:
        ticker = search_query.upper()
        raw_items = yf.Ticker(ticker).news or []
        articles: List[Dict[str, Any]] = []
        links: set[str] = set()

        for item in raw_items:
            article = self._parse_yfinance_item(item, ticker)
            if not article:
                continue
            link = article.get("link") or article["headline"]
            if link in links:
                continue
            links.add(link)
            articles.append(article)
            if len(articles) >= self.scrape_num_articles:
                break

        if not articles:
            logger.warning(f"No news articles found for {ticker}.")
            return []

        self.mongo_client.insert_many(self.collection_name, articles)
        logger.info(f"Inserted {len(articles)} articles for {ticker} into MongoDB.")
        return articles

    def scrape_all_tickers(self, tickers):
        for ticker in tickers:
            logger.info(f"Scraping news for ticker: {ticker}")
            try:
                self.scrape_articles(ticker)
            except Exception as e:
                logger.error(f"Error while scraping news for {ticker}: {e}")


if __name__ == "__main__":
    load_dotenv()
    scraper = NewsScraper(
        collection_name=os.getenv("COLLECTION_NAME"),
        scrape_num_articles=int(os.getenv("SCRAPE_NUM_ARTICLES", 5)),
    )
    scraper.scrape_all_tickers(["AAPL", "NVDA"])
