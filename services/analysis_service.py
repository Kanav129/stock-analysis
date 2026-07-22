from __future__ import annotations

import math
import os
import threading
from datetime import datetime, timedelta
from typing import Any

from rag_graphs.research_graph.graph import app as research_graph
from rag_graphs.research_graph.nodes.persist_report import persist_report
from rag_graphs.research_graph.nodes.synthesize_decision import synthesize_decision
from db.db_factory import get_db_client
from services import run_checkpoint_service as rcs
from services.report_service import ReportService
from services.universe_service import UniverseService
from utils.logger import logger

# Core research-report pipeline stages (Run Analysis = full core report per ticker)
STAGE_LABELS = {
    "gather_prices": "Market / technicals",
    "gather_fundamentals": "Fundamentals",
    "gather_news": "News / macro",
    "gather_sentiment": "Sentiment",
    "synthesize_decision": "Decision synthesis",
    "persist": "Saving report & rating",
}

# Ordered for progress % within a ticker (core path only)
STAGES = [
    "gather_prices",
    "gather_fundamentals",
    "gather_news",
    "gather_sentiment",
    "synthesize_decision",
    "persist",
]

RESCORE_STAGES = ["synthesize_decision", "persist"]
RESCORE_STAGE_LABELS = {
    "synthesize_decision": "Re-scoring decision",
    "persist": "Saving score & rating",
}

# From Jul 19 full-universe core-report batch: consecutive report gaps averaged ~189s/ticker.
DEFAULT_CORE_SECONDS_PER_TICKER = 190
DEFAULT_RESCORE_SECONDS_PER_TICKER = 45
DEFAULT_TIMEOUT_BUFFER = 1.2  # +20% headroom
MIN_ANALYSIS_TIMEOUT_SECONDS = 10 * 60


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def compute_analysis_timeouts(ticker_count: int, *, mode: str = "core_report") -> dict[str, int]:
    """Total analysis budget: avg_sec_per_ticker × n × buffer."""
    n = max(1, int(ticker_count))
    buffer = _env_float("ANALYSIS_TIMEOUT_BUFFER", DEFAULT_TIMEOUT_BUFFER)
    if buffer < 1.0:
        buffer = DEFAULT_TIMEOUT_BUFFER

    absolute = os.getenv("ANALYSIS_TIMEOUT_SECONDS")
    if absolute and absolute.strip():
        try:
            total = max(MIN_ANALYSIS_TIMEOUT_SECONDS, int(absolute))
            return {"per_ticker": max(1, total // n), "total": total, "mode": mode}
        except ValueError:
            pass

    if mode == "rescore":
        per = _env_float(
            "ANALYSIS_RESCORE_SECONDS_PER_TICKER",
            DEFAULT_RESCORE_SECONDS_PER_TICKER,
        )
    else:
        per = _env_float(
            "ANALYSIS_CORE_SECONDS_PER_TICKER",
            DEFAULT_CORE_SECONDS_PER_TICKER,
        )

    total = max(MIN_ANALYSIS_TIMEOUT_SECONDS, int(math.ceil(n * per * buffer)))
    return {
        "per_ticker": int(math.ceil(per)),
        "total": total,
        "mode": mode,
    }


class AnalysisService:
    """Singleton runner: generates a core research report per ticker (full multi-analyst
    pipeline + decision), which also updates desk ratings. Never uses the lightweight
    news+price-only analysis graph.
    """

    _instance: AnalysisService | None = None
    _lock = threading.Lock()

    def __new__(cls) -> AnalysisService:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self.universe = UniverseService()
        self._last_run: datetime | None = None
        self._state_lock = threading.Lock()
        self._progress: dict[str, Any] = self._idle_progress()
        self._worker: threading.Thread | None = None
        self._initialized = True

    @staticmethod
    def _idle_progress() -> dict[str, Any]:
        return {
            "running": False,
            "status": "idle",  # idle | pending | running | done | failed | cancelled
            "mode": "core_report",
            "tickers": [],
            "total": 0,
            "current_index": 0,
            "current_ticker": None,
            "stage": None,
            "stage_label": None,
            "completed": [],
            "errors": [],
            "percent": 0,
            "message": "",
            "started_at": None,
            "finished_at": None,
            "last_run": None,
            "cancel_requested": False,
        }

    @property
    def last_run(self) -> datetime | None:
        return self._last_run

    def get_status(self) -> dict[str, Any]:
        with self._state_lock:
            snap = dict(self._progress)
            snap["last_run"] = (
                self._last_run.isoformat() if self._last_run else snap.get("last_run")
            )
            snap.pop("cancel_requested", None)
        day = rcs.today_key()
        checkpoint = rcs.load_analysis(day)
        universe = [str(ticker).upper() for ticker in self.universe.get_tickers()]
        completed = [
            dict(item)
            for item in (checkpoint or {}).get("completed") or []
            if isinstance(item, dict) and item.get("ticker")
        ]
        checkpoint_done = {
            str(item["ticker"]).upper()
            for item in completed
        }
        try:
            db_done = self._core_reports_done_today(day)
        except Exception as exc:
            logger.warning("Could not read today's core reports for status: %s", exc)
            db_done = set()
        effective_checkpoint = dict(checkpoint or {})
        effective_checkpoint["completed"] = completed + [
            {"ticker": ticker}
            for ticker in sorted(db_done)
            if ticker not in checkpoint_done
        ]
        snap["daily"] = rcs.daily_analysis_summary(
            effective_checkpoint,
            universe,
        )
        return snap

    def _core_reports_done_today(self, day: str | None = None) -> set[str]:
        """Core reports already persisted in today's HKT calendar window."""
        start, end = rcs.day_bounds_utc(day)
        db = get_db_client()
        rows, _ = db.fetch_query(
            """
            SELECT DISTINCT ticker
            FROM stock_reports
            WHERE report_type = 'core'
              AND created_at >= %s
              AND created_at < %s
            """,
            (start, end),
        )
        return {str(row[0]).upper() for row in rows if row and row[0]}

    def _update(self, **kwargs: Any) -> None:
        with self._state_lock:
            self._progress.update(kwargs)
            total = self._progress.get("total") or 0
            stage = self._progress.get("stage")
            done = len(self._progress.get("completed") or [])
            mode = self._progress.get("mode")
            stage_list = RESCORE_STAGES if mode == "rescore" else STAGES
            stage_frac = 0.0
            if stage in stage_list and self._progress.get("running"):
                stage_frac = (stage_list.index(stage) + 1) / len(stage_list)
            if total:
                pct = (done + stage_frac) / total * 100
            else:
                pct = 0
            self._progress["percent"] = max(0, min(100, round(pct, 1)))

    def request_cancel(self) -> dict[str, Any]:
        with self._state_lock:
            if not self._progress.get("running"):
                return self.get_status()
            self._progress["cancel_requested"] = True
            self._progress["message"] = "Cancel requested — finishing current step…"
        return self.get_status()

    def _cancel_requested(self) -> bool:
        with self._state_lock:
            return bool(self._progress.get("cancel_requested"))

    def start(
        self,
        tickers: list[str] | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Start core-report analysis for the universe in a background thread."""
        with self._state_lock:
            if self._progress.get("running"):
                return {
                    "started": False,
                    "message": "An analysis is already running.",
                    **{k: v for k, v in self.get_status().items() if k != "cancel_requested"},
                }

        target = [t.upper() for t in (tickers or self.universe.get_tickers())]
        if not target:
            return {
                "started": False,
                "message": "No tickers in universe for analysis.",
                "status": "idle",
                "running": False,
            }

        day = rcs.today_key()
        checkpoint = rcs.load_analysis(day)
        checkpoint_completed = [
            dict(item)
            for item in (checkpoint or {}).get("completed") or []
            if isinstance(item, dict) and item.get("ticker")
        ]
        checkpoint_done = {
            str(item["ticker"]).upper() for item in checkpoint_completed
        }
        db_done = set() if force else self._core_reports_done_today(day)
        done = set() if force else checkpoint_done | db_done
        todo = [ticker for ticker in target if ticker not in done]

        if not force and not todo:
            summary_checkpoint = dict(
                checkpoint or rcs.empty_analysis_checkpoint(target)
            )
            summary_checkpoint.update(
                status="completed",
                tickers=target,
                completed=checkpoint_completed
                + [
                    {"ticker": ticker}
                    for ticker in target
                    if ticker in db_done and ticker not in checkpoint_done
                ],
            )
            rcs.save_analysis(summary_checkpoint, day=day)
            rcs.mark_last_analysis_date(day)
            return {
                **self.get_status(),
                "started": False,
                "reason": "already_completed_today",
                "date": day,
                "finished_at": (checkpoint or {}).get("finished_at"),
                "message": "Core analysis already completed today.",
                "daily": rcs.daily_analysis_summary(summary_checkpoint, target),
            }

        if force:
            checkpoint = rcs.empty_analysis_checkpoint(target)
        else:
            checkpoint = dict(
                checkpoint or rcs.empty_analysis_checkpoint(target)
            )
            checkpoint.update(
                status="running",
                tickers=target,
                errors=[],
                finished_at=None,
            )
            checkpoint.setdefault("started_at", datetime.utcnow().isoformat())
            checkpoint["completed"] = checkpoint_completed + [
                {"ticker": ticker}
                for ticker in target
                if ticker in db_done and ticker not in checkpoint_done
            ]
        rcs.save_analysis(checkpoint, day=day)

        started_at = datetime.utcnow()
        timeouts = compute_analysis_timeouts(len(todo), mode="core_report")
        self._update(
            running=True,
            status="pending",
            mode="core_report",
            tickers=todo,
            total=len(todo),
            current_index=0,
            current_ticker=None,
            stage=None,
            stage_label=None,
            completed=[],
            errors=[],
            percent=0,
            message=f"Queued core reports for {len(todo)} ticker(s)…",
            started_at=started_at.isoformat(),
            finished_at=None,
            cancel_requested=False,
            deadline_at=(started_at + timedelta(seconds=timeouts["total"])).isoformat(),
        )

        self._worker = threading.Thread(
            target=self._run_worker,
            args=(todo, timeouts, day, checkpoint),
            daemon=True,
            name="analysis-core-report-worker",
        )
        self._worker.start()
        logger.info(
            "Core-report analysis started for %s tickers (timeout=%ss ≈ %.1f min)",
            len(todo),
            timeouts["total"],
            timeouts["total"] / 60,
        )
        return {
            "started": True,
            "message": f"Generating core reports + ratings for {len(todo)} ticker(s).",
            "resumed": bool(done),
            "skipped": len(target) - len(todo),
            "date": day,
            "checkpoint": checkpoint,
            "timeouts": timeouts,
            **self.get_status(),
        }

    def run(self, tickers: list[str] | None = None) -> dict[str, Any]:
        """Sync entrypoint used by scheduled pipeline — blocks until finished."""
        result = self.start(tickers)
        if not result.get("started"):
            return result
        if self._worker:
            self._worker.join()
        status = self.get_status()
        return {
            "analyzed": status.get("completed") or [],
            "errors": status.get("errors") or [],
            "last_run": status.get("last_run"),
            "count": len(status.get("completed") or []),
            "status": status.get("status"),
            "message": status.get("message"),
        }

    def _run_worker(
        self,
        target: list[str],
        timeouts: dict[str, int] | None = None,
        day: str | None = None,
        checkpoint_seed: dict[str, Any] | None = None,
    ) -> None:
        self._update(
            status="running",
            message="Generating core research reports…",
        )
        completed: list[dict[str, Any]] = []
        checkpoint = dict(
            checkpoint_seed or rcs.empty_analysis_checkpoint(target)
        )
        checkpoint_completed = list(checkpoint.get("completed") or [])
        errors: list[dict[str, str]] = list(checkpoint.get("errors") or [])
        timeouts = timeouts or compute_analysis_timeouts(len(target), mode="core_report")
        started_at = datetime.utcnow()
        deadline = started_at + timedelta(seconds=timeouts["total"])

        def save_checkpoint(status: str | None = None, *, finished: bool = False) -> None:
            if status:
                checkpoint["status"] = status
            checkpoint["completed"] = list(checkpoint_completed)
            checkpoint["errors"] = list(errors)
            if finished:
                checkpoint["finished_at"] = datetime.utcnow().isoformat()
            rcs.save_analysis(checkpoint, day=day)

        try:
            for i, ticker in enumerate(target):
                if datetime.utcnow() >= deadline:
                    msg = (
                        f"Analysis timed out after {timeouts['total']}s "
                        f"({len(completed)}/{len(target)} reports done). "
                        "Try fewer tickers or raise ANALYSIS_CORE_SECONDS_PER_TICKER."
                    )
                    logger.error(msg)
                    errors.append({"ticker": "*", "error": "timeout"})
                    save_checkpoint("partial", finished=True)
                    self._update(
                        running=False,
                        status="failed",
                        message=msg,
                        errors=list(errors),
                        finished_at=datetime.utcnow().isoformat(),
                        current_ticker=None,
                        stage=None,
                        stage_label=None,
                    )
                    return

                if self._cancel_requested():
                    save_checkpoint("cancelled", finished=True)
                    self._update(
                        status="cancelled",
                        running=False,
                        message=f"Cancelled after {len(completed)}/{len(target)} reports.",
                        finished_at=datetime.utcnow().isoformat(),
                        percent=round(len(completed) / len(target) * 100, 1) if target else 0,
                    )
                    logger.info("Core-report analysis cancelled by user.")
                    return

                self._update(
                    current_index=i,
                    current_ticker=ticker,
                    stage=None,
                    stage_label=None,
                    message=f"Core report {ticker} ({i + 1}/{len(target)})…",
                )
                try:
                    rating_result = self._run_ticker_core_report(ticker)
                    completed.append({
                        "ticker": ticker,
                        "rating": rating_result.get("rating"),
                        "score": rating_result.get("score"),
                        "report_id": rating_result.get("report_id"),
                    })
                    checkpoint_completed.append(dict(completed[-1]))
                    save_checkpoint()
                    self._update(completed=list(completed))
                except Exception as exc:
                    if self._cancel_requested() or "cancelled" in str(exc).lower():
                        save_checkpoint("cancelled", finished=True)
                        self._update(
                            status="cancelled",
                            running=False,
                            message=f"Cancelled after {len(completed)}/{len(target)} reports.",
                            finished_at=datetime.utcnow().isoformat(),
                            percent=round(len(completed) / len(target) * 100, 1) if target else 0,
                            current_ticker=None,
                            stage=None,
                            stage_label=None,
                        )
                        logger.info("Core-report analysis cancelled by user.")
                        return
                    logger.error(f"Core report analysis failed for {ticker}: {exc}")
                    errors.append({"ticker": ticker, "error": str(exc)})
                    save_checkpoint("partial" if checkpoint_completed else "failed")
                    self._update(errors=list(errors))

            failed = len(errors)
            msg = f"Done — {len(completed)} core report(s)"
            if failed:
                msg += f", {failed} failed"
            universe = [str(ticker).upper() for ticker in checkpoint.get("tickers") or target]
            done = {
                str(item.get("ticker", "")).upper()
                for item in checkpoint_completed
                if isinstance(item, dict)
            }
            complete = not failed and all(ticker in done for ticker in universe)
            checkpoint_status = "completed" if complete else (
                "partial" if checkpoint_completed else "failed"
            )
            save_checkpoint(checkpoint_status, finished=True)
            if complete:
                self._last_run = datetime.utcnow()
                rcs.mark_last_analysis_date(day)
            self._update(
                running=False,
                status="done" if complete else ("done" if completed else "failed"),
                current_ticker=None,
                stage=None,
                stage_label=None,
                message=msg,
                finished_at=checkpoint["finished_at"],
                last_run=self._last_run.isoformat() if self._last_run else None,
                percent=100 if complete else (
                    round(len(completed) / len(target) * 100, 1) if target else 0
                ),
                completed=list(completed),
                errors=list(errors),
            )
            logger.info(f"Core-report analysis finished: {msg}")
        except Exception as exc:
            logger.error(f"Analysis worker crashed: {exc}")
            errors.append({"ticker": "*", "error": str(exc)})
            save_checkpoint("failed", finished=True)
            self._update(
                running=False,
                status="failed",
                message=str(exc),
                finished_at=datetime.utcnow().isoformat(),
            )

    def _run_ticker_core_report(self, ticker: str) -> dict[str, Any]:
        """Stream the core research graph; rating comes from full multi-analyst synthesis."""
        final: dict[str, Any] = {"ticker": ticker}
        initial = {
            "ticker": ticker.upper(),
            "report_type": "core",
            "sections_markdown": {},
            "errors": [],
        }
        for event in research_graph.stream(initial, stream_mode="updates"):
            if self._cancel_requested():
                raise RuntimeError("Analysis cancelled")
            if not isinstance(event, dict):
                continue
            for stage, payload in event.items():
                label = STAGE_LABELS.get(stage, stage.replace("_", " ").title())
                updates: dict[str, Any] = {
                    "stage_label": label,
                    "message": f"{ticker}: {label}…",
                }
                if stage in STAGES:
                    updates["stage"] = stage
                self._update(**updates)
                if isinstance(payload, dict):
                    final.update(payload)
        return final

    def start_rescore(self, tickers: list[str] | None = None) -> dict[str, Any]:
        """Re-run decision synthesis only from saved report sections (no data gather)."""
        with self._state_lock:
            if self._progress.get("running"):
                return {
                    "started": False,
                    "message": "An analysis is already running.",
                    **self.get_status(),
                }

        reports = ReportService().list_latest_reports_by_ticker()
        by_ticker = {r["ticker"]: r for r in reports}
        if tickers:
            target = [t.upper() for t in tickers if t.upper() in by_ticker]
        else:
            target = sorted(by_ticker.keys())

        if not target:
            return {
                "started": False,
                "message": "No saved reports to rescore.",
                "status": "idle",
                "running": False,
            }

        started_at = datetime.utcnow()
        self._update(
            running=True,
            status="pending",
            mode="rescore",
            tickers=target,
            total=len(target),
            current_index=0,
            current_ticker=None,
            stage=None,
            stage_label=None,
            completed=[],
            errors=[],
            percent=0,
            message=f"Queued rescore for {len(target)} ticker(s)…",
            started_at=started_at.isoformat(),
            finished_at=None,
            cancel_requested=False,
        )

        self._worker = threading.Thread(
            target=self._run_rescore_worker,
            args=(target, by_ticker),
            daemon=True,
            name="analysis-rescore-worker",
        )
        self._worker.start()
        return {
            "started": True,
            "message": f"Rescoring ratings for {len(target)} ticker(s) from saved reports.",
            **self.get_status(),
        }

    def _run_rescore_worker(
        self,
        target: list[str],
        by_ticker: dict[str, dict[str, Any]],
    ) -> None:
        self._update(status="running", message="Rescoring from saved reports…")
        completed: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []

        try:
            for i, ticker in enumerate(target):
                if self._cancel_requested():
                    self._update(
                        status="cancelled",
                        running=False,
                        message=f"Cancelled after {len(completed)}/{len(target)} rescores.",
                        finished_at=datetime.utcnow().isoformat(),
                        percent=round(len(completed) / len(target) * 100, 1) if target else 0,
                    )
                    return

                report = by_ticker[ticker]
                self._update(
                    current_index=i,
                    current_ticker=ticker,
                    stage="synthesize_decision",
                    stage_label=RESCORE_STAGE_LABELS["synthesize_decision"],
                    message=f"Rescore {ticker} ({i + 1}/{len(target)})…",
                )
                try:
                    result = self._rescore_ticker(report)
                    completed.append({
                        "ticker": ticker,
                        "rating": result.get("rating"),
                        "score": result.get("score"),
                        "report_id": result.get("report_id"),
                    })
                    self._update(completed=list(completed), stage="persist",
                                 stage_label=RESCORE_STAGE_LABELS["persist"])
                except Exception as exc:
                    if self._cancel_requested() or "cancelled" in str(exc).lower():
                        self._update(
                            status="cancelled",
                            running=False,
                            message=f"Cancelled after {len(completed)}/{len(target)} rescores.",
                            finished_at=datetime.utcnow().isoformat(),
                            percent=round(len(completed) / len(target) * 100, 1) if target else 0,
                            current_ticker=None,
                            stage=None,
                            stage_label=None,
                        )
                        return
                    logger.error(f"Rescore failed for {ticker}: {exc}")
                    errors.append({"ticker": ticker, "error": str(exc)})
                    self._update(errors=list(errors))

            self._last_run = datetime.utcnow()
            failed = len(errors)
            msg = f"Done — rescored {len(completed)} ticker(s)"
            if failed:
                msg += f", {failed} failed"
            self._update(
                running=False,
                status="done" if not failed or completed else "failed",
                current_ticker=None,
                stage=None,
                stage_label=None,
                message=msg,
                finished_at=self._last_run.isoformat(),
                last_run=self._last_run.isoformat(),
                percent=100,
                completed=list(completed),
                errors=list(errors),
            )
            logger.info(f"Rescore finished: {msg}")
        except Exception as exc:
            logger.error(f"Rescore worker crashed: {exc}")
            self._update(
                running=False,
                status="failed",
                message=str(exc),
                finished_at=datetime.utcnow().isoformat(),
            )

    def _rescore_ticker(self, report: dict[str, Any]) -> dict[str, Any]:
        """Synthesize + persist using existing report sections only."""
        if self._cancel_requested():
            raise RuntimeError("Analysis cancelled")

        ticker = report["ticker"]
        state: dict[str, Any] = {
            "ticker": ticker,
            "report_type": report.get("report_type") or "core",
            "report_id": report["id"],
            "sections_markdown": report.get("sections") or {},
            "factor_scores": report.get("factor_scores") or {},
            "live_price": report.get("live_price") or 0.0,
            "fundamental_data": {},
            "market_data": {},
            "sentiment_data": {},
            "errors": [],
        }

        self._update(
            stage="synthesize_decision",
            stage_label=RESCORE_STAGE_LABELS["synthesize_decision"],
            message=f"{ticker}: Re-scoring decision…",
        )
        decision = synthesize_decision(state)  # type: ignore[arg-type]
        state.update(decision)

        if self._cancel_requested():
            raise RuntimeError("Analysis cancelled")

        self._update(
            stage="persist",
            stage_label=RESCORE_STAGE_LABELS["persist"],
            message=f"{ticker}: Saving score & rating…",
        )
        persist_out = persist_report(state)  # type: ignore[arg-type]
        state.update(persist_out)
        return state


# Module-level singleton
analysis_service = AnalysisService()
