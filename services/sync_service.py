from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Any, Callable, Optional

from rag_graphs.news_rag_graph.ingestion import DocumentSyncManager
from scraper.scraper_factory import NewsScraperFactory, StockScraperFactory
from services.universe_service import UniverseService
from utils.logger import logger

ProgressCb = Callable[[str, int, int], None]

STAGE_WEIGHTS = {
    "news": 35,
    "prices": 50,
    "vectors": 15,
}
STAGE_PRIOR = {
    "news": 0,
    "prices": 35,
    "vectors": 85,
}


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
            "total": 0,
            "current_index": 0,
            "current_ticker": None,
            "stage": None,
            "stage_label": None,
            "completed": [],
            "errors": [],
            "percent": 0,
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

    def _set_stage_progress(
        self,
        stage: str,
        stage_label: str,
        index: int,
        total: int,
        ticker: str | None,
        message: str,
    ) -> None:
        prior = STAGE_PRIOR.get(stage, 0)
        weight = STAGE_WEIGHTS.get(stage, 0)
        if total <= 0:
            frac = 1.0
        elif index <= 0:
            frac = 0.0
        elif index >= total:
            frac = 1.0
        else:
            frac = (index - 1) / total + (0.5 / total)
        percent = round(prior + weight * min(1.0, max(0.0, frac)), 1)
        self._update(
            stage=stage,
            stage_label=stage_label,
            current_index=max(0, index - 1) if index else 0,
            current_ticker=ticker,
            message=message,
            percent=min(99.0, percent) if self._running and percent < 100 else percent,
        )

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
            message=f"Starting sync for {len(target)} ticker(s)…",
            tickers=target,
            total=len(target),
            current_index=0,
            current_ticker=None,
            stage="news",
            stage_label="News",
            completed=[],
            errors=[],
            percent=0,
            started_at=datetime.utcnow().isoformat(),
            finished_at=None,
        )

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._running = False
            self._update(status="error", message="No event loop available to start sync", percent=0)
            return {"started": False, "message": "No event loop available", **self.get_status()}

        self._task = loop.create_task(self._run_worker(target))
        logger.info(f"Background sync started for {len(target)} tickers")
        return {
            "started": True,
            "message": f"Sync started for {len(target)} ticker(s).",
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
        completed: list[str] = []
        total = len(target)
        try:
            loop = asyncio.get_running_loop()
            stock_scraper = StockScraperFactory().create_scraper()
            news_scraper = NewsScraperFactory().create_scraper(
                collection_name=os.getenv("COLLECTION_NAME"),
                scrape_num_articles=int(os.getenv("SCRAPE_NUM_ARTICLES", 5)),
            )

            logger.info(f"Data sync running for {total} tickers: {target}")

            def _news_progress(ticker: str, index: int, total_n: int) -> None:
                done = target[: max(0, index - 1)]
                self._update(completed=list(done))
                self._set_stage_progress(
                    "news",
                    "News",
                    index,
                    total_n,
                    ticker,
                    f"Fetching news · {ticker} ({index}/{total_n})",
                )

            def _price_progress(ticker: str, index: int, total_n: int) -> None:
                # index is 1-based "now working"; prior tickers are done for prices
                done = target[: max(0, index - 1)]
                completed.clear()
                completed.extend(done)
                self._update(completed=list(completed))
                self._set_stage_progress(
                    "prices",
                    "Prices",
                    index,
                    total_n,
                    ticker,
                    f"Syncing prices · {ticker} ({index}/{total_n})",
                )

            scrape_timeout_s = int(os.getenv("SYNC_SCRAPE_TIMEOUT_SECONDS", str(50 * 60)))

            # Sequential stages so the UI can show a clear stage pipeline
            self._set_stage_progress("news", "News", 0, total, None, "Fetching news…")
            await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: news_scraper.scrape_all_tickers(target, on_progress=_news_progress),
                ),
                timeout=scrape_timeout_s // 2,
            )

            self._set_stage_progress("prices", "Prices", 0, total, None, "Syncing prices…")
            await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: stock_scraper.scrape_all_tickers(target, on_progress=_price_progress),
                ),
                timeout=scrape_timeout_s // 2,
            )

            completed.clear()
            completed.extend(target)
            self._update(
                stage="vectors",
                stage_label="Vectors",
                current_ticker=None,
                message="Indexing news vectors…",
                percent=85.0,
                completed=list(completed),
            )
            try:
                await loop.run_in_executor(None, DocumentSyncManager().sync_documents)
            except Exception as exc:
                logger.error(f"Chroma sync failed: {exc}")
                errors.append({"ticker": "*", "error": f"chroma_sync: {exc}"})

            self._last_sync = datetime.utcnow()
            self._update(
                status="completed",
                stage="vectors",
                stage_label="Vectors",
                message=f"Synced news and prices for {total} ticker(s).",
                errors=errors,
                completed=list(completed) if completed else list(target),
                current_ticker=None,
                percent=100,
                finished_at=datetime.utcnow().isoformat(),
                last_sync=self._last_sync.isoformat(),
            )
            logger.info(f"Background sync completed for {total} tickers")
        except asyncio.TimeoutError:
            logger.error("Background sync timed out")
            self._update(
                status="error",
                message="Sync timed out. Try fewer tickers or re-run.",
                errors=[{"ticker": "*", "error": "timeout"}],
                finished_at=datetime.utcnow().isoformat(),
            )
        except Exception as exc:
            logger.error(f"Background sync failed: {exc}")
            self._update(
                status="error",
                message=str(exc),
                errors=[{"ticker": "*", "error": str(exc)}],
                finished_at=datetime.utcnow().isoformat(),
            )
        finally:
            self._running = False
            self._status["running"] = False


sync_service = SyncService()
