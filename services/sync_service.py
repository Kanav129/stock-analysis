from __future__ import annotations

import asyncio
import math
import os
import threading
from datetime import datetime
from typing import Any, Callable, Optional

from rag_graphs.news_rag_graph.ingestion import DocumentSyncManager
from scraper.scraper_factory import NewsScraperFactory, StockScraperFactory
from services import run_checkpoint_service as rcs
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

# Empirically derived from GitHub daily-sync runs on 2026-07-21 and 2026-07-22
# (22 tickers): news ≈ 665s total (~30s/ticker); prices ≈ 90–390s/ticker depending on
# 5d vs 1mo yfinance window — mean of measured price syncs ≈ 200s/ticker.
DEFAULT_NEWS_SECONDS_PER_TICKER = 30
DEFAULT_PRICE_SECONDS_PER_TICKER = 200
DEFAULT_TIMEOUT_BUFFER = 1.2  # +20% headroom
MIN_STAGE_TIMEOUT_SECONDS = 5 * 60
VECTORS_TIMEOUT_SECONDS = 10 * 60


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def compute_stage_timeouts(ticker_count: int) -> dict[str, int]:
    """Per-stage scrape timeouts: avg_sec_per_ticker × n × buffer (+ floors)."""
    n = max(1, int(ticker_count))
    news_per = _env_float("SYNC_NEWS_SECONDS_PER_TICKER", DEFAULT_NEWS_SECONDS_PER_TICKER)
    price_per = _env_float("SYNC_PRICE_SECONDS_PER_TICKER", DEFAULT_PRICE_SECONDS_PER_TICKER)
    buffer = _env_float("SYNC_TIMEOUT_BUFFER", DEFAULT_TIMEOUT_BUFFER)
    if buffer < 1.0:
        buffer = DEFAULT_TIMEOUT_BUFFER

    # Absolute override keeps older deployments working if set explicitly.
    absolute = os.getenv("SYNC_SCRAPE_TIMEOUT_SECONDS")
    if absolute and absolute.strip():
        try:
            total = max(MIN_STAGE_TIMEOUT_SECONDS * 2, int(absolute))
            half = max(MIN_STAGE_TIMEOUT_SECONDS, total // 2)
            return {
                "news": half,
                "prices": half,
                "vectors": VECTORS_TIMEOUT_SECONDS,
                "total": half * 2 + VECTORS_TIMEOUT_SECONDS,
            }
        except ValueError:
            pass

    news = max(MIN_STAGE_TIMEOUT_SECONDS, int(math.ceil(n * news_per * buffer)))
    prices = max(MIN_STAGE_TIMEOUT_SECONDS, int(math.ceil(n * price_per * buffer)))
    vectors = VECTORS_TIMEOUT_SECONDS
    return {
        "news": news,
        "prices": prices,
        "vectors": vectors,
        "total": news + prices + vectors,
    }


def compute_resume_timeouts(
    news_n: int,
    prices_n: int,
    need_vectors: bool,
) -> dict[str, int]:
    """Size each stage timeout from only the work remaining for that stage."""
    news = compute_stage_timeouts(max(1, news_n))["news"] if news_n else 0
    prices = compute_stage_timeouts(max(1, prices_n))["prices"] if prices_n else 0
    vectors = VECTORS_TIMEOUT_SECONDS if need_vectors else 0
    return {
        "news": news,
        "prices": prices,
        "vectors": vectors,
        "total": news + prices + vectors,
    }


class SyncService:
    def __init__(self) -> None:
        self.universe = UniverseService()
        self._last_sync: Optional[datetime] = None
        self._running = False
        self._run_generation = 0
        self._generation_lock = threading.Lock()
        self._task: Optional[asyncio.Task] = None
        self._cancel_requested = False
        self._status: dict[str, Any] = {
            "status": "idle",
            "running": False,
            "message": None,
            "detail": None,
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
        checkpoint = rcs.load_sync()
        # After a Render recycle, RAM is idle but the checkpoint may still say
        # "running". Heal to partial so UI/cron know they can resume.
        if checkpoint and checkpoint.get("status") == "running" and not self._running:
            checkpoint = dict(checkpoint)
            checkpoint["status"] = "partial"
            try:
                rcs.save_sync(checkpoint)
            except Exception as exc:
                logger.warning("Could not heal stale sync checkpoint: %s", exc)
        universe = [str(ticker).upper() for ticker in self.universe.get_tickers()]
        return {
            **self._status,
            "running": self._running,
            "last_sync": self._last_sync.isoformat() if self._last_sync else self._status.get("last_sync"),
            "daily": rcs.daily_sync_summary(
                checkpoint,
                universe,
            ),
        }

    def _update(self, **kwargs: Any) -> None:
        self._status.update(kwargs)
        self._status["running"] = self._running

    def request_cancel(self) -> dict[str, Any]:
        """Soft-cancel: finish current ticker, keep checkpoint for resume."""
        if not self._running:
            return self.get_status()
        self._cancel_requested = True
        self._update(message="Cancel requested — finishing current ticker…")
        return self.get_status()

    def _cancel_flag(self) -> bool:
        return bool(self._cancel_requested)

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

    def start(
        self,
        tickers: Optional[list[str]] = None,
        force: bool = False,
    ) -> dict[str, Any]:
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

        day = rcs.today_key()
        checkpoint = rcs.load_sync(day)
        if not force and rcs.is_sync_complete_for_universe(checkpoint, target):
            daily = rcs.daily_sync_summary(checkpoint, target)
            return {
                **self.get_status(),
                "started": False,
                "reason": "already_completed_today",
                "date": day,
                "finished_at": (checkpoint or {}).get("finished_at"),
                "message": "Sync already completed today.",
                "daily": daily,
            }

        todos = rcs.sync_todos(checkpoint, target, force=force)
        news_todo = list(todos["news_todo"])
        prices_todo = list(todos["prices_todo"])
        need_vectors = bool(todos["need_vectors"])

        if not news_todo and not prices_todo and not need_vectors:
            checkpoint = dict(checkpoint or rcs.empty_sync_checkpoint(target))
            if not rcs.is_sync_complete_for_universe(checkpoint, target):
                checkpoint.update(
                    status="partial",
                    tickers=target,
                    finished_at=datetime.utcnow().isoformat(),
                )
                rcs.save_sync(checkpoint, day=day)
                return {
                    **self.get_status(),
                    "started": False,
                    "reason": "incomplete_coverage",
                    "date": day,
                    "message": "Sync finished, but some tickers are incomplete.",
                    "daily": rcs.daily_sync_summary(checkpoint, target),
                }
            checkpoint.update(
                status="completed",
                tickers=target,
                finished_at=checkpoint.get("finished_at") or datetime.utcnow().isoformat(),
            )
            rcs.save_sync(checkpoint, day=day)
            daily = rcs.daily_sync_summary(checkpoint, target)
            return {
                **self.get_status(),
                "started": False,
                "reason": "already_completed_today",
                "date": day,
                "finished_at": checkpoint.get("finished_at"),
                "message": "Sync already completed today.",
                "daily": daily,
            }

        if force or not checkpoint:
            checkpoint = rcs.empty_sync_checkpoint(target)
        else:
            checkpoint = dict(checkpoint)
            checkpoint.update(
                status="running",
                tickers=target,
                errors=[],
                finished_at=None,
            )
            checkpoint.setdefault("news_done", [])
            checkpoint.setdefault("prices_done", [])
            checkpoint.setdefault("vectors_done", False)
            checkpoint.setdefault("started_at", datetime.utcnow().isoformat())
        rcs.save_sync(checkpoint, day=day)

        self._running = True
        self._cancel_requested = False
        timeouts = compute_resume_timeouts(
            len(news_todo),
            len(prices_todo),
            need_vectors,
        )
        self._update(
            status="running",
            message=f"Starting sync for {len(target)} ticker(s)…",
            tickers=target,
            total=len(target),
            current_index=0,
            current_ticker=None,
            stage="news" if news_todo else ("prices" if prices_todo else "vectors"),
            stage_label="News" if news_todo else ("Prices" if prices_todo else "Vectors"),
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
            checkpoint["status"] = "error"
            checkpoint["errors"] = [{"ticker": "*", "error": "No event loop available"}]
            rcs.save_sync(checkpoint, day=day)
            return {"started": False, "message": "No event loop available", **self.get_status()}

        with self._generation_lock:
            self._run_generation += 1
            generation = self._run_generation
        self._task = loop.create_task(
            self._run_worker(
                target,
                news_todo,
                prices_todo,
                need_vectors,
                checkpoint_seed=checkpoint,
                day=day,
                generation=generation,
            )
        )
        logger.info(
            "Background sync started for %s tickers (timeouts news=%ss prices=%ss)",
            len(target),
            timeouts["news"],
            timeouts["prices"],
        )
        return {
            "started": True,
            "message": f"Sync started for {len(target)} ticker(s).",
            "resumed": bool(todos["resumed"]),
            "skipped": {
                "news": len(target) - len(news_todo),
                "prices": len(target) - len(prices_todo),
            },
            "date": day,
            "checkpoint": checkpoint,
            "timeouts": timeouts,
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

    async def _run_worker(
        self,
        target: list[str],
        news_todo: list[str],
        prices_todo: list[str],
        need_vectors: bool,
        *,
        checkpoint_seed: dict[str, Any],
        day: str,
        generation: int | None = None,
    ) -> None:
        generation = self._run_generation if generation is None else generation
        checkpoint = dict(checkpoint_seed)
        errors: list[dict[str, str]] = list(checkpoint.get("errors") or [])
        completed: list[str] = []
        total = len(target)
        abandoned_by_worker = False

        def _is_current() -> bool:
            with self._generation_lock:
                return generation == self._run_generation

        def _save_if_current(data: dict[str, Any]) -> bool:
            with self._generation_lock:
                if generation != self._run_generation:
                    return False
                rcs.save_sync(data, day=day)
                return True

        def _abandon_current() -> bool:
            nonlocal abandoned_by_worker
            with self._generation_lock:
                if generation != self._run_generation:
                    return False
                self._run_generation += 1
                abandoned_by_worker = True
                return True

        def _should_continue() -> bool:
            return _is_current() and not self._cancel_flag()

        def _finalize_cancelled(message: str) -> None:
            finished_at = datetime.utcnow().isoformat()
            checkpoint.update(
                status="cancelled",
                errors=errors,
                finished_at=finished_at,
            )
            if not _save_if_current(checkpoint):
                return
            self._update(
                status="cancelled",
                message=message,
                detail=None,
                errors=errors,
                completed=list(completed),
                current_ticker=None,
                finished_at=finished_at,
            )
            logger.info("Background sync cancelled by user (checkpoint kept for resume)")

        try:
            loop = asyncio.get_running_loop()

            logger.info(f"Data sync running for {total} tickers: {target}")

            def _checkpoint_ticker(field: str, ticker: str) -> None:
                with self._generation_lock:
                    if generation != self._run_generation:
                        return
                    done = checkpoint.setdefault(field, [])
                    normalized = ticker.upper()
                    if normalized not in {str(item).upper() for item in done}:
                        done.append(normalized)
                    rcs.save_sync(checkpoint, day=day)

            def _news_progress(ticker: str, index: int, total_n: int) -> None:
                if not _is_current():
                    return
                done = news_todo[: max(0, index - 1)]
                self._update(completed=list(done))
                msg = f"Fetching news · {ticker} ({index}/{total_n})"
                if self._cancel_flag():
                    msg = "Cancel requested — finishing current ticker…"
                self._set_stage_progress(
                    "news",
                    "News",
                    index,
                    total_n,
                    ticker,
                    msg,
                )

            def _price_progress(ticker: str, index: int, total_n: int) -> None:
                if not _is_current():
                    return
                # index is 1-based "now working"; prior tickers are done for prices
                done = prices_todo[: max(0, index - 1)]
                completed.clear()
                completed.extend(done)
                self._update(
                    completed=list(completed),
                    detail=f"{ticker} · starting price ladder…",
                )
                msg = f"Syncing prices · {ticker} ({index}/{total_n})"
                if self._cancel_flag():
                    msg = "Cancel requested — finishing current ticker…"
                self._set_stage_progress(
                    "prices",
                    "Prices",
                    index,
                    total_n,
                    ticker,
                    msg,
                )

            def _price_detail(detail: str) -> None:
                if not _is_current():
                    return
                self._update(detail=detail)

            timeouts = compute_resume_timeouts(
                len(news_todo),
                len(prices_todo),
                need_vectors,
            )
            logger.info(
                "Sync timeouts for %s tickers: news=%ss prices=%ss vectors=%ss (total=%ss)",
                total,
                timeouts["news"],
                timeouts["prices"],
                timeouts["vectors"],
                timeouts["total"],
            )

            # Sequential stages so the UI can show a clear stage pipeline
            if news_todo:
                news_scraper = NewsScraperFactory().create_scraper(
                    collection_name=os.getenv("COLLECTION_NAME"),
                    scrape_num_articles=int(os.getenv("SCRAPE_NUM_ARTICLES", 5)),
                )
                self._set_stage_progress(
                    "news",
                    "News",
                    0,
                    len(news_todo),
                    None,
                    "Fetching news…",
                )
                await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: news_scraper.scrape_all_tickers(
                            news_todo,
                            on_progress=_news_progress,
                            on_ticker_done=lambda ticker: _checkpoint_ticker(
                                "news_done",
                                ticker,
                            ),
                            should_continue=_should_continue,
                        ),
                    ),
                    timeout=timeouts["news"],
                )
                if not _is_current():
                    return
                if self._cancel_flag():
                    _finalize_cancelled("Sync cancelled. Progress saved — Sync again to resume.")
                    return

            if prices_todo:
                stock_scraper = StockScraperFactory().create_scraper()
                self._set_stage_progress(
                    "prices",
                    "Prices",
                    0,
                    len(prices_todo),
                    None,
                    "Syncing prices…",
                )
                self._update(detail="Preparing price sync…")
                await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: stock_scraper.scrape_all_tickers(
                            prices_todo,
                            on_progress=_price_progress,
                            on_detail=_price_detail,
                            on_ticker_done=lambda ticker: _checkpoint_ticker(
                                "prices_done",
                                ticker,
                            ),
                            should_continue=_should_continue,
                        ),
                    ),
                    timeout=timeouts["prices"],
                )
                if _is_current():
                    self._update(detail=None)
                if not _is_current():
                    return
                if self._cancel_flag():
                    _finalize_cancelled("Sync cancelled. Progress saved — Sync again to resume.")
                    return

            completed.clear()
            completed.extend(target)
            if self._cancel_flag():
                _finalize_cancelled("Sync cancelled. Progress saved — Sync again to resume.")
                return
            if need_vectors:
                self._update(
                    stage="vectors",
                    stage_label="Vectors",
                    current_ticker=None,
                    message="Indexing news vectors…",
                    percent=85.0,
                    completed=list(completed),
                )
                try:
                    await asyncio.wait_for(
                        loop.run_in_executor(None, DocumentSyncManager().sync_documents),
                        timeout=timeouts["vectors"],
                    )
                    if not _is_current():
                        return
                    checkpoint["vectors_done"] = True
                    _save_if_current(checkpoint)
                except Exception as exc:
                    if not _is_current():
                        return
                    logger.error(f"Chroma sync failed: {exc}")
                    errors.append({"ticker": "*", "error": f"chroma_sync: {exc}"})
                    checkpoint.update(status="partial", errors=errors, vectors_done=False)
                    terminal_checkpoint = dict(checkpoint)
                    if not _abandon_current():
                        return
                    rcs.save_sync(terminal_checkpoint, day=day)
                    self._update(
                        status="partial",
                        stage="vectors",
                        stage_label="Vectors",
                        message="News and prices synced, but vector indexing failed.",
                        errors=errors,
                        completed=list(completed),
                        current_ticker=None,
                        percent=85.0,
                        finished_at=datetime.utcnow().isoformat(),
                    )
                    return

            if not rcs.is_sync_complete_for_universe(checkpoint, target):
                finished_at = datetime.utcnow().isoformat()
                checkpoint.update(
                    status="partial",
                    errors=errors,
                    finished_at=finished_at,
                )
                if not _save_if_current(checkpoint):
                    return
                self._update(
                    status="partial",
                    message="Sync finished, but some tickers are incomplete.",
                    errors=errors,
                    completed=list(completed),
                    current_ticker=None,
                    percent=99.0,
                    finished_at=finished_at,
                )
                return

            self._last_sync = datetime.utcnow()
            finished_at = self._last_sync.isoformat()
            checkpoint.update(
                status="completed",
                errors=errors,
                vectors_done=True,
                finished_at=finished_at,
            )
            if not _save_if_current(checkpoint):
                return
            rcs.mark_last_sync_date(day)
            if not _is_current():
                return
            self._update(
                status="completed",
                stage="vectors",
                stage_label="Vectors",
                message=f"Synced news and prices for {total} ticker(s).",
                detail=None,
                errors=errors,
                completed=list(completed) if completed else list(target),
                current_ticker=None,
                percent=100,
                finished_at=finished_at,
                last_sync=self._last_sync.isoformat(),
            )
            logger.info(f"Background sync completed for {total} tickers")
        except asyncio.TimeoutError:
            if not _is_current():
                return
            logger.error("Background sync timed out")
            errors.append({"ticker": "*", "error": "timeout"})
            checkpoint.update(status="partial", errors=errors)
            terminal_checkpoint = dict(checkpoint)
            if not _abandon_current():
                return
            rcs.save_sync(terminal_checkpoint, day=day)
            self._update(
                status="partial",
                message="Sync timed out. Try fewer tickers or re-run.",
                errors=errors,
                finished_at=datetime.utcnow().isoformat(),
            )
        except Exception as exc:
            if not _is_current():
                return
            logger.error(f"Background sync failed: {exc}")
            errors.append({"ticker": "*", "error": str(exc)})
            checkpoint.update(status="error", errors=errors)
            terminal_checkpoint = dict(checkpoint)
            if not _abandon_current():
                return
            rcs.save_sync(terminal_checkpoint, day=day)
            self._update(
                status="error",
                message=str(exc),
                errors=errors,
                finished_at=datetime.utcnow().isoformat(),
            )
        finally:
            if _is_current() or abandoned_by_worker:
                self._running = False
                self._status["running"] = False


sync_service = SyncService()
