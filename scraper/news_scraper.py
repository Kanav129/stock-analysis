import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import yfinance as yf
from dotenv import load_dotenv

from db.mongo_db import MongoDBClient
from scraper.concurrency import sync_max_concurrent
from scraper.generic_scraper import GenericScraper
from utils.logger import logger

# One hung Yahoo news lookup must not block the rest of the daily sync.
# Measured news fetches are ~30s/ticker; 60s leaves headroom without a multi-hour stall.
NEWS_FETCH_TIMEOUT_SECONDS = 60


def news_ticker_timeout_seconds() -> float:
    raw = os.getenv("SYNC_NEWS_TICKER_TIMEOUT_SECONDS", "")
    if raw.strip():
        try:
            value = float(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return float(NEWS_FETCH_TIMEOUT_SECONDS)


class NewsScraper(GenericScraper):
    def __init__(self, collection_name, scrape_num_articles=1):
        self.collection_name = collection_name
        self.scrape_num_articles = scrape_num_articles
        self.mongo_client = MongoDBClient()
        self._insert_guards: Dict[str, Callable[[], bool]] = {}

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

        guard = self._insert_guards.get(ticker)
        if guard is not None and not guard():
            logger.warning(f"Dropping news for {ticker} after the fetch timed out.")
            return []

        self.mongo_client.insert_many(self.collection_name, articles)
        logger.info(f"Inserted {len(articles)} articles for {ticker} into MongoDB.")
        return articles

    def _scrape_one(self, ticker: str) -> None:
        """Fetch one ticker, giving up if Yahoo news does not return in time.

        The underlying yfinance call can block past any socket timeout. The
        worker thread is a daemon so a late response cannot keep the process
        alive, and it is not allowed to insert articles after we have moved on.
        """
        timeout = news_ticker_timeout_seconds()
        error: list[BaseException] = []
        abandoned = threading.Event()
        key = ticker.upper()
        self._insert_guards[key] = lambda: not abandoned.is_set()

        def target() -> None:
            try:
                self.scrape_articles(ticker)
            except BaseException as exc:  # re-raised on the caller thread
                error.append(exc)

        thread = threading.Thread(target=target, name=f"news-{ticker}", daemon=True)
        thread.start()
        thread.join(timeout)
        if thread.is_alive():
            abandoned.set()
            raise TimeoutError(f"news fetch timed out after {timeout:g}s")
        if error:
            self._insert_guards.pop(key, None)
            raise error[0]
        self._insert_guards.pop(key, None)

    @staticmethod
    def _record_failure(
        ticker: str,
        exc: BaseException,
        on_ticker_failed: Optional[Callable[..., None]],
    ) -> None:
        logger.error(f"Error while scraping news for {ticker}: {exc}")
        if on_ticker_failed is None:
            return
        try:
            on_ticker_failed(ticker, exc)
        except Exception:
            logger.exception(f"News failure callback failed for {ticker}")

    def scrape_all_tickers(
        self,
        tickers,
        on_progress=None,
        on_ticker_done=None,
        on_ticker_failed=None,
        should_continue=None,
    ):
        total = len(tickers)
        max_c = sync_max_concurrent()
        if max_c <= 1:
            for index, ticker in enumerate(tickers, start=1):
                if should_continue is not None and not should_continue():
                    logger.info("News scrape stopped early (cancel requested)")
                    return
                logger.info(f"Scraping news for ticker: {ticker} ({index}/{total})")
                if on_progress:
                    try:
                        on_progress(ticker, index, total)
                    except Exception:
                        pass
                try:
                    self._scrape_one(ticker)
                except Exception as e:
                    self._record_failure(ticker, e, on_ticker_failed)
                    continue
                if on_ticker_done:
                    try:
                        on_ticker_done(ticker)
                    except Exception:
                        pass
            return

        done_count = 0
        lock = threading.Lock()

        def _one(ticker: str) -> str:
            logger.info(f"Scraping news for ticker: {ticker}")
            self._scrape_one(ticker)
            return ticker

        with ThreadPoolExecutor(max_workers=max_c) as pool:
            futures = {}
            for ticker in tickers:
                if should_continue is not None and not should_continue():
                    logger.info("News scrape stopped early (cancel requested)")
                    break
                futures[pool.submit(_one, ticker)] = ticker
            for fut in as_completed(futures):
                if should_continue is not None and not should_continue():
                    for pending in futures:
                        pending.cancel()
                    logger.info("News scrape stopped early (cancel requested)")
                    break
                ticker = futures[fut]
                try:
                    fut.result()
                except Exception as e:
                    self._record_failure(ticker, e, on_ticker_failed)
                    continue
                with lock:
                    done_count += 1
                    n = done_count
                if on_progress:
                    try:
                        on_progress(ticker, n, total)
                    except Exception:
                        pass
                if on_ticker_done:
                    try:
                        on_ticker_done(ticker)
                    except Exception:
                        pass


if __name__ == "__main__":
    load_dotenv()
    scraper = NewsScraper(
        collection_name=os.getenv("COLLECTION_NAME"),
        scrape_num_articles=int(os.getenv("SCRAPE_NUM_ARTICLES", 5)),
    )
    scraper.scrape_all_tickers(["AAPL", "NVDA"])
