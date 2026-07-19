from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Any, Optional

from rag_graphs.news_rag_graph.ingestion import DocumentSyncManager
from scraper.scraper_factory import NewsScraperFactory, StockScraperFactory
from services.universe_service import UniverseService
from utils.logger import logger


class SyncService:
    def __init__(self) -> None:
        self.universe = UniverseService()
        self._last_sync: Optional[datetime] = None
        self._running = False

    @property
    def last_sync(self) -> Optional[datetime]:
        return self._last_sync

    @property
    def is_running(self) -> bool:
        return self._running

    async def sync_data(self, tickers: Optional[list[str]] = None) -> dict[str, Any]:
        if self._running:
            return {
                "started": False,
                "message": "A sync is already in progress.",
                "last_sync": self._last_sync.isoformat() if self._last_sync else None,
            }

        target = [t.upper() for t in (tickers or self.universe.get_tickers())]
        if not target:
            return {
                "started": False,
                "message": "No tickers to sync. Add tickers to your watchlist first.",
                "tickers": [],
            }

        self._running = True
        errors: list[dict[str, str]] = []

        try:
            loop = asyncio.get_event_loop()
            stock_scraper = StockScraperFactory().create_scraper()
            news_scraper = NewsScraperFactory().create_scraper(
                collection_name=os.getenv("COLLECTION_NAME"),
                scrape_num_articles=int(os.getenv("SCRAPE_NUM_ARTICLES", 5)),
            )

            logger.info(f"Manual data sync starting for {len(target)} tickers: {target}")

            await asyncio.gather(
                loop.run_in_executor(None, news_scraper.scrape_all_tickers, target),
                loop.run_in_executor(None, stock_scraper.scrape_all_tickers, target),
            )

            try:
                DocumentSyncManager().sync_documents()
            except Exception as exc:
                logger.error(f"Chroma sync failed: {exc}")
                errors.append({"stage": "chroma_sync", "error": str(exc)})

            self._last_sync = datetime.utcnow()
            return {
                "started": True,
                "message": f"Synced news and price data for {len(target)} ticker(s).",
                "tickers": target,
                "last_sync": self._last_sync.isoformat(),
                "errors": errors,
            }
        except Exception as exc:
            logger.error(f"Manual data sync failed: {exc}")
            return {
                "started": False,
                "message": str(exc),
                "tickers": target,
                "errors": [{"stage": "sync", "error": str(exc)}],
            }
        finally:
            self._running = False


sync_service = SyncService()
