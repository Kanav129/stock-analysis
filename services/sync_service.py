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
        self._task: Optional[asyncio.Task] = None
        self._status: dict[str, Any] = {
            "status": "idle",
            "running": False,
            "message": None,
            "tickers": [],
            "errors": [],
            "started_at": None,
            "finished_at": None,
            "last_sync": None,
        }

    @property
    def last_sync(self) -> Optional[datetime]:
        return self._last_sync

    @property
    def is_running(self) -> bool:
        return self._running

    def get_status(self) -> dict[str, Any]:
        return {
            **self._status,
            "running": self._running,
            "last_sync": self._last_sync.isoformat() if self._last_sync else self._status.get("last_sync"),
        }

    def _update(self, **kwargs: Any) -> None:
        self._status.update(kwargs)
        self._status["running"] = self._running

    def start(self, tickers: Optional[list[str]] = None) -> dict[str, Any]:
        """Kick off sync in the background; poll GET /sync/status until done."""
        if self._running:
            return {
                "started": False,
                "message": "A sync is already in progress.",
                **self.get_status(),
            }

        target = [t.upper() for t in (tickers or self.universe.get_tickers())]
        if not target:
            return {
                "started": False,
                "message": "No tickers to sync. Add tickers to your watchlist first.",
                "tickers": [],
                **self.get_status(),
            }

        self._running = True
        self._update(
            status="running",
            message=f"Syncing news & prices for {len(target)} ticker(s)…",
            tickers=target,
            errors=[],
            started_at=datetime.utcnow().isoformat(),
            finished_at=None,
        )

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._running = False
            self._update(status="error", message="No event loop available to start sync")
            return {"started": False, "message": "No event loop available", **self.get_status()}

        self._task = loop.create_task(self._run_worker(target))
        logger.info(f"Background sync started for {len(target)} tickers")
        return {
            "started": True,
            "message": f"Sync started for {len(target)} ticker(s). Poll /sync/status for progress.",
            **self.get_status(),
        }

    async def sync_data(self, tickers: Optional[list[str]] = None) -> dict[str, Any]:
        """Start sync and wait until it finishes (used by in-process schedulers)."""
        result = self.start(tickers)
        if not result.get("started") and not self._running:
            return result
        while self._running:
            await asyncio.sleep(1)
        status = self.get_status()
        return {
            "started": status.get("status") == "completed",
            "message": status.get("message"),
            "tickers": status.get("tickers") or [],
            "last_sync": status.get("last_sync"),
            "errors": status.get("errors") or [],
            **status,
        }

    async def _run_worker(self, target: list[str]) -> None:
        errors: list[dict[str, str]] = []
        try:
            loop = asyncio.get_running_loop()
            stock_scraper = StockScraperFactory().create_scraper()
            news_scraper = NewsScraperFactory().create_scraper(
                collection_name=os.getenv("COLLECTION_NAME"),
                scrape_num_articles=int(os.getenv("SCRAPE_NUM_ARTICLES", 5)),
            )

            logger.info(f"Data sync running for {len(target)} tickers: {target}")
            self._update(message=f"Scraping news & prices ({len(target)} tickers)…")

            def _price_progress(ticker: str, index: int, total: int) -> None:
                self._update(
                    message=f"Syncing prices {index}/{total}: {ticker} (news in parallel)…"
                )

            # Bound scrape phase so a stuck yfinance/DB call cannot leave running=true forever.
            scrape_timeout_s = int(os.getenv("SYNC_SCRAPE_TIMEOUT_SECONDS", str(50 * 60)))
            await asyncio.wait_for(
                asyncio.gather(
                    loop.run_in_executor(None, news_scraper.scrape_all_tickers, target),
                    loop.run_in_executor(
                        None,
                        lambda: stock_scraper.scrape_all_tickers(
                            target, on_progress=_price_progress
                        ),
                    ),
                ),
                timeout=scrape_timeout_s,
            )

            self._update(message="Syncing news vectors…")
            try:
                await loop.run_in_executor(None, DocumentSyncManager().sync_documents)
            except Exception as exc:
                logger.error(f"Chroma sync failed: {exc}")
                errors.append({"stage": "chroma_sync", "error": str(exc)})

            self._last_sync = datetime.utcnow()
            self._update(
                status="completed",
                message=f"Synced news and price data for {len(target)} ticker(s).",
                errors=errors,
                finished_at=datetime.utcnow().isoformat(),
                last_sync=self._last_sync.isoformat(),
            )
            logger.info(f"Background sync completed for {len(target)} tickers")
        except Exception as exc:
            logger.error(f"Background sync failed: {exc}")
            self._update(
                status="error",
                message=str(exc),
                errors=[{"stage": "sync", "error": str(exc)}],
                finished_at=datetime.utcnow().isoformat(),
            )
        finally:
            self._running = False
            self._status["running"] = False


sync_service = SyncService()
