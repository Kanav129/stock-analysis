"""Durable desk LLM job queue (core analysis, deep dive, rescore)."""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from psycopg2.extras import Json

from db.db_factory import get_db_client
from services import run_checkpoint_service as rcs
from services.universe_service import UniverseService
from utils.logger import logger

JOB_CORE = "core_analysis"
JOB_DEEP = "deep_dive"
JOB_RESCORE = "rescore"
ACTIVE_STATUSES = ("queued", "running")
TERMINAL_RECENT_SECONDS = 120

STAGE_LABELS = {
    "gather_prices": "Market / technicals",
    "gather_fundamentals": "Fundamentals",
    "gather_news": "News / macro",
    "gather_sentiment": "Sentiment",
    "gather_flows": "Flows / ownership",
    "gather_policy": "Policy",
    "gather_lockup": "Lockup / insider",
    "run_kronos": "Kronos forecast",
    "debate": "Debate",
    "synthesize_decision": "Decision synthesis",
    "persist": "Saving report & rating",
}

CORE_STAGES = [
    "gather_prices",
    "gather_fundamentals",
    "gather_news",
    "gather_sentiment",
    "synthesize_decision",
    "persist",
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Any) -> Optional[str]:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)


def _max_concurrent() -> int:
    raw = os.getenv("JOB_MAX_CONCURRENT", "1")
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def _row_to_job(row: tuple, cols: list[str]) -> dict[str, Any]:
    data = dict(zip(cols, row))
    progress = data.get("progress") or {}
    if isinstance(progress, str):
        progress = json.loads(progress)
    result = data.get("result") or {}
    if isinstance(result, str):
        result = json.loads(result)
    return {
        "id": str(data["id"]),
        "job_type": data["job_type"],
        "ticker": data["ticker"],
        "status": data["status"],
        "cancel_requested": bool(data.get("cancel_requested")),
        "progress": progress if isinstance(progress, dict) else {},
        "result": result if isinstance(result, dict) else {},
        "error": data.get("error"),
        "created_at": _iso(data.get("created_at")),
        "started_at": _iso(data.get("started_at")),
        "finished_at": _iso(data.get("finished_at")),
        "updated_at": _iso(data.get("updated_at")),
    }


class JobQueueService:
    """Postgres-backed queue with in-process workers (concurrency capped)."""

    _instance: JobQueueService | None = None
    _lock = threading.Lock()

    def __new__(cls) -> JobQueueService:
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
        self._worker_stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._started = False
        self._initialized = True

    def ensure_started(self) -> None:
        """Heal interrupted rows and start the drain worker (idempotent)."""
        with self._lock:
            if self._started:
                return
            self._heal_running_jobs()
            self._worker_stop.clear()
            self._worker = threading.Thread(
                target=self._worker_loop,
                name="desk-job-queue",
                daemon=True,
            )
            self._worker.start()
            self._started = True
            logger.info(
                "Job queue worker started (max_concurrent=%s)",
                _max_concurrent(),
            )

    def _heal_running_jobs(self) -> None:
        db = get_db_client()
        # Soft-cancel in progress → cancelled; others re-queue for resume.
        db.execute_query(
            """
            UPDATE desk_jobs
            SET status = 'cancelled',
                finished_at = NOW(),
                updated_at = NOW(),
                error = COALESCE(error, 'Interrupted on restart (cancel was requested)')
            WHERE status = 'running' AND cancel_requested = TRUE
            """
        )
        db.execute_query(
            """
            UPDATE desk_jobs
            SET status = 'queued',
                started_at = NULL,
                updated_at = NOW(),
                progress = COALESCE(progress, '{}'::jsonb) || '{"healed": true}'::jsonb
            WHERE status = 'running' AND cancel_requested = FALSE
            """
        )
        # Legacy interrupted → queued
        db.execute_query(
            """
            UPDATE desk_jobs
            SET status = 'queued', updated_at = NOW()
            WHERE status = 'interrupted'
            """
        )

    def limits(self) -> dict[str, int]:
        db = get_db_client()
        rows, _ = db.fetch_query(
            """
            SELECT
              COUNT(*) FILTER (WHERE status = 'running') AS running,
              COUNT(*) FILTER (WHERE status = 'queued') AS queued
            FROM desk_jobs
            """
        )
        running = int(rows[0][0] or 0) if rows else 0
        queued = int(rows[0][1] or 0) if rows else 0
        return {
            "max_concurrent": _max_concurrent(),
            "running": running,
            "queued": queued,
        }

    def count_active(self, job_type: str | None = None) -> int:
        """Cheap COUNT of queued/running jobs (optional type filter)."""
        db = get_db_client()
        if job_type:
            rows, _ = db.fetch_query(
                """
                SELECT COUNT(*) FROM desk_jobs
                WHERE status IN ('queued', 'running') AND job_type = %s
                """,
                (job_type,),
            )
        else:
            rows, _ = db.fetch_query(
                """
                SELECT COUNT(*) FROM desk_jobs
                WHERE status IN ('queued', 'running')
                """
            )
        return int(rows[0][0] or 0) if rows else 0

    def list_jobs(self) -> list[dict[str, Any]]:
        db = get_db_client()
        rows, cols = db.fetch_query(
            """
            SELECT id, job_type, ticker, status, cancel_requested,
                   progress, result, error,
                   created_at, started_at, finished_at, updated_at
            FROM desk_jobs
            WHERE status IN ('queued', 'running')
               OR (
                 status IN ('done', 'failed', 'cancelled', 'interrupted')
                 AND finished_at IS NOT NULL
                 AND finished_at > NOW() - INTERVAL '120 seconds'
               )
            ORDER BY
              CASE status
                WHEN 'running' THEN 0
                WHEN 'queued' THEN 1
                ELSE 2
              END,
              created_at ASC
            """,
        )
        return [_row_to_job(r, cols) for r in rows]

    def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        db = get_db_client()
        rows, cols = db.fetch_query(
            """
            SELECT id, job_type, ticker, status, cancel_requested,
                   progress, result, error,
                   created_at, started_at, finished_at, updated_at
            FROM desk_jobs WHERE id = %s
            """,
            (job_id,),
        )
        if not rows:
            return None
        return _row_to_job(rows[0], cols)

    def find_active(self, ticker: str, job_type: str) -> Optional[dict[str, Any]]:
        db = get_db_client()
        rows, cols = db.fetch_query(
            """
            SELECT id, job_type, ticker, status, cancel_requested,
                   progress, result, error,
                   created_at, started_at, finished_at, updated_at
            FROM desk_jobs
            WHERE ticker = %s AND job_type = %s AND status IN ('queued', 'running')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (ticker.upper(), job_type),
        )
        if not rows:
            return None
        return _row_to_job(rows[0], cols)

    def enqueue(
        self,
        job_type: str,
        tickers: list[str],
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        """Enqueue one job per ticker. Dedupes against active queued/running."""
        self.ensure_started()
        if job_type not in (JOB_CORE, JOB_DEEP, JOB_RESCORE):
            raise ValueError(f"Invalid job_type: {job_type}")

        symbols = []
        seen: set[str] = set()
        for raw in tickers:
            t = (raw or "").strip().upper()
            if t and t not in seen:
                seen.add(t)
                symbols.append(t)

        if not symbols:
            return {
                "started": False,
                "enqueued": [],
                "reused": [],
                "message": "No tickers to enqueue.",
            }

        # Daily gate for bulk core analysis
        skipped_completed: list[str] = []
        if job_type == JOB_CORE and not force:
            day = rcs.today_key()
            checkpoint = rcs.load_analysis(day)
            checkpoint_done = {
                str(item["ticker"]).upper()
                for item in (checkpoint or {}).get("completed") or []
                if isinstance(item, dict) and item.get("ticker")
            }
            from services.analysis_service import analysis_service

            try:
                db_done = analysis_service._core_reports_done_today(day)
            except Exception:
                db_done = set()
            done = checkpoint_done | db_done
            remaining = [t for t in symbols if t not in done]
            skipped_completed = [t for t in symbols if t in done]
            symbols = remaining
            if not symbols:
                target = [t.upper() for t in tickers]
                summary_checkpoint = dict(
                    checkpoint or rcs.empty_analysis_checkpoint(target)
                )
                completed = [
                    dict(item)
                    for item in (checkpoint or {}).get("completed") or []
                    if isinstance(item, dict) and item.get("ticker")
                ]
                completed_tickers = {
                    str(item["ticker"]).upper() for item in completed
                }
                summary_checkpoint.update(
                    status="completed",
                    tickers=target,
                    completed=completed
                    + [
                        {"ticker": ticker}
                        for ticker in target
                        if ticker in db_done and ticker not in completed_tickers
                    ],
                )
                rcs.save_analysis(summary_checkpoint, day=day)
                rcs.mark_last_analysis_date(day)
                return {
                    "started": False,
                    "reason": "already_completed_today",
                    "date": day,
                    "enqueued": [],
                    "reused": [],
                    "skipped_completed": skipped_completed,
                    "message": "Core analysis already completed today.",
                    "jobs": [],
                }

        if job_type == JOB_CORE:
            day = rcs.today_key()
            target = list(
                dict.fromkeys(
                    [t.upper() for t in (tickers or self.universe.get_tickers())]
                )
            )
            checkpoint = rcs.load_analysis(day)
            if force:
                checkpoint = rcs.empty_analysis_checkpoint(target)
            else:
                checkpoint = dict(checkpoint or rcs.empty_analysis_checkpoint(target))
            checkpoint.update(
                status="running",
                tickers=target,
                finished_at=None,
            )
            checkpoint.setdefault("started_at", _utcnow().isoformat())
            rcs.save_analysis(checkpoint, day=day)

        enqueued: list[dict[str, Any]] = []
        reused: list[dict[str, Any]] = []
        db = get_db_client()

        for ticker in symbols:
            existing = self.find_active(ticker, job_type)
            if existing:
                reused.append(existing)
                continue
            job_id = str(uuid4())
            db.execute_query(
                """
                INSERT INTO desk_jobs (
                    id, job_type, ticker, status, cancel_requested,
                    progress, result, created_at, updated_at
                ) VALUES (%s, %s, %s, 'queued', FALSE, %s, %s, NOW(), NOW())
                """,
                (
                    job_id,
                    job_type,
                    ticker,
                    Json({"message": "Queued"}),
                    Json({}),
                ),
            )
            job = self.get_job(job_id)
            if job:
                enqueued.append(job)

        return {
            "started": bool(enqueued or reused),
            "enqueued": enqueued,
            "reused": reused,
            "skipped_completed": skipped_completed,
            "message": (
                f"Queued {len(enqueued)} job(s)"
                + (f", reused {len(reused)}" if reused else "")
                + (f", skipped {len(skipped_completed)} done today" if skipped_completed else "")
            ),
            "jobs": enqueued + reused,
            "limits": self.limits(),
        }

    def cancel(self, job_id: str) -> dict[str, Any]:
        self.ensure_started()
        job = self.get_job(job_id)
        if not job:
            return {"ok": False, "error": "not_found"}
        if job["status"] == "queued":
            db = get_db_client()
            db.execute_query(
                """
                UPDATE desk_jobs
                SET status = 'cancelled',
                    finished_at = NOW(),
                    updated_at = NOW(),
                    progress = COALESCE(progress, '{}'::jsonb) || '{"message": "Cancelled (queued)"}'::jsonb
                WHERE id = %s AND status = 'queued'
                """,
                (job_id,),
            )
            return {"ok": True, "job": self.get_job(job_id)}
        if job["status"] == "running":
            db = get_db_client()
            db.execute_query(
                """
                UPDATE desk_jobs
                SET cancel_requested = TRUE,
                    updated_at = NOW(),
                    progress = COALESCE(progress, '{}'::jsonb)
                      || '{"message": "Cancel requested — finishing current step…"}'::jsonb
                WHERE id = %s AND status = 'running'
                """,
                (job_id,),
            )
            return {"ok": True, "job": self.get_job(job_id)}
        return {"ok": True, "job": job, "message": "already_terminal"}

    def cancel_all(self) -> dict[str, Any]:
        self.ensure_started()
        db = get_db_client()
        db.execute_query(
            """
            UPDATE desk_jobs
            SET status = 'cancelled',
                finished_at = NOW(),
                updated_at = NOW(),
                progress = COALESCE(progress, '{}'::jsonb) || '{"message": "Cancelled (queued)"}'::jsonb
            WHERE status = 'queued'
            """
        )
        db.execute_query(
            """
            UPDATE desk_jobs
            SET cancel_requested = TRUE,
                updated_at = NOW(),
                progress = COALESCE(progress, '{}'::jsonb)
                  || '{"message": "Cancel requested — finishing current step…"}'::jsonb
            WHERE status = 'running'
            """
        )
        return {"ok": True, "limits": self.limits(), "jobs": self.list_jobs()}

    def _cancel_requested(self, job_id: str) -> bool:
        db = get_db_client()
        rows, _ = db.fetch_query(
            "SELECT cancel_requested FROM desk_jobs WHERE id = %s",
            (job_id,),
        )
        return bool(rows and rows[0][0])

    def _set_progress(self, job_id: str, **fields: Any) -> None:
        progress = {k: v for k, v in fields.items() if v is not None}
        db = get_db_client()
        db.execute_query(
            """
            UPDATE desk_jobs
            SET progress = COALESCE(progress, '{}'::jsonb) || %s::jsonb,
                updated_at = NOW()
            WHERE id = %s
            """,
            (Json(progress), job_id),
        )

    def _finish(
        self,
        job_id: str,
        status: str,
        *,
        result: Optional[dict] = None,
        error: Optional[str] = None,
        message: Optional[str] = None,
    ) -> None:
        progress = {"message": message, "percent": 100 if status == "done" else None}
        progress = {k: v for k, v in progress.items() if v is not None}
        db = get_db_client()
        if result is not None:
            db.execute_query(
                """
                UPDATE desk_jobs
                SET status = %s,
                    finished_at = NOW(),
                    updated_at = NOW(),
                    error = %s,
                    result = %s,
                    progress = COALESCE(progress, '{}'::jsonb) || %s::jsonb
                WHERE id = %s
                """,
                (status, error, Json(result), Json(progress), job_id),
            )
        else:
            db.execute_query(
                """
                UPDATE desk_jobs
                SET status = %s,
                    finished_at = NOW(),
                    updated_at = NOW(),
                    error = %s,
                    progress = COALESCE(progress, '{}'::jsonb) || %s::jsonb
                WHERE id = %s
                """,
                (status, error, Json(progress), job_id),
            )
        job = self.get_job(job_id)
        if status == "done" and job and job["job_type"] == JOB_CORE:
            self._append_analysis_checkpoint(job["ticker"], result or {})

    def _append_analysis_checkpoint(self, ticker: str, result: dict[str, Any]) -> None:
        day = rcs.today_key()
        checkpoint = dict(rcs.load_analysis(day) or rcs.empty_analysis_checkpoint([]))
        completed = list(checkpoint.get("completed") or [])
        entry = {
            "ticker": ticker.upper(),
            "rating": result.get("rating"),
            "score": result.get("score"),
            "report_id": result.get("report_id"),
        }
        # Replace existing ticker entry if present
        completed = [
            c for c in completed
            if not (isinstance(c, dict) and str(c.get("ticker", "")).upper() == ticker.upper())
        ]
        completed.append(entry)
        checkpoint["completed"] = completed
        tickers = [str(t).upper() for t in (checkpoint.get("tickers") or [])]
        universe = tickers or [str(t).upper() for t in self.universe.get_tickers()]
        done = {str(c.get("ticker", "")).upper() for c in completed if isinstance(c, dict)}
        # Still running if other core jobs queued/running
        limits = self.limits()
        active_core = self._count_active_type(JOB_CORE)
        if active_core == 0 and universe and all(t in done for t in universe):
            checkpoint["status"] = "completed"
            checkpoint["finished_at"] = _utcnow().isoformat()
            rcs.mark_last_analysis_date(day)
        else:
            checkpoint["status"] = "running" if active_core else "partial"
        rcs.save_analysis(checkpoint, day=day)

    def _count_active_type(self, job_type: str) -> int:
        db = get_db_client()
        rows, _ = db.fetch_query(
            """
            SELECT COUNT(*) FROM desk_jobs
            WHERE job_type = %s AND status IN ('queued', 'running')
            """,
            (job_type,),
        )
        return int(rows[0][0] or 0) if rows else 0

    def _claim_next(self) -> Optional[dict[str, Any]]:
        db = get_db_client()
        max_c = _max_concurrent()
        with db.checkout() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT COUNT(*) FROM desk_jobs WHERE status = 'running'"
                )
                running = int(cur.fetchone()[0] or 0)
                if running >= max_c:
                    conn.commit()
                    return None
                cur.execute(
                    """
                    SELECT id FROM desk_jobs
                    WHERE status = 'queued'
                    ORDER BY created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                    """
                )
                row = cur.fetchone()
                if not row:
                    conn.commit()
                    return None
                job_id = row[0]
                cur.execute(
                    """
                    UPDATE desk_jobs
                    SET status = 'running',
                        started_at = NOW(),
                        updated_at = NOW(),
                        progress = COALESCE(progress, '{}'::jsonb)
                          || '{"message": "Starting…", "percent": 0}'::jsonb
                    WHERE id = %s AND status = 'queued'
                    RETURNING id
                    """,
                    (job_id,),
                )
                claimed = cur.fetchone()
                conn.commit()
                if not claimed:
                    return None
            except Exception:
                conn.rollback()
                raise
            finally:
                cur.close()
        return self.get_job(str(job_id))

    def _worker_loop(self) -> None:
        while not self._worker_stop.is_set():
            try:
                job = self._claim_next()
                if job is None:
                    time.sleep(0.5)
                    continue
                # Run in this worker thread (concurrency = number of claim loops
                # would need a pool; with max=1 one thread is enough. For max>1,
                # spawn a short-lived thread per job.)
                if _max_concurrent() == 1:
                    self._execute_job(job)
                else:
                    t = threading.Thread(
                        target=self._execute_job,
                        args=(job,),
                        daemon=True,
                        name=f"desk-job-{job['id'][:8]}",
                    )
                    t.start()
                    # Brief pause so counts update before next claim
                    time.sleep(0.2)
            except Exception as exc:
                logger.error("Job queue worker error: %s", exc)
                time.sleep(1.0)

    def _execute_job(self, job: dict[str, Any]) -> None:
        job_id = job["id"]
        ticker = job["ticker"]
        job_type = job["job_type"]
        logger.info("Job %s starting %s %s", job_id[:8], job_type, ticker)
        try:
            if self._cancel_requested(job_id):
                self._finish(job_id, "cancelled", message="Cancelled before start")
                return
            if job_type == JOB_CORE:
                result = self._run_core(job_id, ticker)
            elif job_type == JOB_DEEP:
                result = self._run_deep(job_id, ticker)
            elif job_type == JOB_RESCORE:
                result = self._run_rescore(job_id, ticker)
            else:
                raise ValueError(f"Unknown job_type {job_type}")

            if self._cancel_requested(job_id):
                self._finish(job_id, "cancelled", message="Cancelled", result=result)
                return
            self._finish(
                job_id,
                "done",
                result=result,
                message="Done",
            )
            logger.info(
                "Job %s done %s %s rating=%s",
                job_id[:8],
                job_type,
                ticker,
                (result or {}).get("rating"),
            )
        except Exception as exc:
            if self._cancel_requested(job_id) or "cancelled" in str(exc).lower():
                self._finish(job_id, "cancelled", message="Cancelled", error=str(exc))
                logger.info("Job %s cancelled %s %s", job_id[:8], job_type, ticker)
                return
            logger.error("Job %s failed %s %s: %s", job_id[:8], job_type, ticker, exc)
            self._finish(job_id, "failed", error=str(exc), message=str(exc))

    def _run_core(self, job_id: str, ticker: str) -> dict[str, Any]:
        from rag_graphs.research_graph.graph import app as research_graph

        final: dict[str, Any] = {"ticker": ticker}
        initial = {
            "ticker": ticker.upper(),
            "report_type": "core",
            "sections_markdown": {},
            "errors": [],
        }
        for event in research_graph.stream(initial, stream_mode="updates"):
            if self._cancel_requested(job_id):
                raise RuntimeError("Job cancelled")
            if not isinstance(event, dict):
                continue
            for stage, payload in event.items():
                label = STAGE_LABELS.get(stage, stage.replace("_", " ").title())
                percent = 0
                if stage in CORE_STAGES:
                    percent = round((CORE_STAGES.index(stage) + 1) / len(CORE_STAGES) * 100, 1)
                self._set_progress(
                    job_id,
                    stage=stage if stage in CORE_STAGES else None,
                    stage_label=label,
                    message=f"{ticker}: {label}…",
                    percent=percent,
                )
                if isinstance(payload, dict):
                    final.update(payload)
        return {
            "ticker": ticker,
            "report_id": final.get("report_id"),
            "rating": final.get("rating"),
            "score": final.get("score"),
        }

    def _run_deep(self, job_id: str, ticker: str) -> dict[str, Any]:
        from rag_graphs.research_graph.graph import app as research_graph

        final: dict[str, Any] = {"ticker": ticker}
        initial = {
            "ticker": ticker.upper(),
            "report_type": "deep",
            "sections_markdown": {},
            "errors": [],
        }
        stages_seen = 0
        for event in research_graph.stream(initial, stream_mode="updates"):
            if self._cancel_requested(job_id):
                raise RuntimeError("Job cancelled")
            if not isinstance(event, dict):
                continue
            for stage, payload in event.items():
                stages_seen += 1
                label = STAGE_LABELS.get(stage, stage.replace("_", " ").title())
                self._set_progress(
                    job_id,
                    stage=stage,
                    stage_label=label,
                    message=f"{ticker}: {label}…",
                    percent=min(95, stages_seen * 8),
                )
                if isinstance(payload, dict):
                    final.update(payload)
        return {
            "ticker": ticker,
            "report_id": final.get("report_id"),
            "rating": final.get("rating"),
            "score": final.get("score"),
        }

    def _run_rescore(self, job_id: str, ticker: str) -> dict[str, Any]:
        from services.report_service import ReportService
        from services.analysis_service import analysis_service

        report = ReportService().get_latest_report(ticker.upper(), "core")
        if not report:
            raise RuntimeError(f"No core report to rescore for {ticker}")
        self._set_progress(
            job_id,
            stage="synthesize_decision",
            stage_label="Re-scoring decision",
            message=f"Rescore {ticker}…",
            percent=40,
        )
        if self._cancel_requested(job_id):
            raise RuntimeError("Job cancelled")
        result = analysis_service._rescore_ticker(report)
        self._set_progress(
            job_id,
            stage="persist",
            stage_label="Saving score & rating",
            message=f"Saving {ticker}…",
            percent=90,
        )
        return {
            "ticker": ticker,
            "report_id": result.get("report_id") or report.get("id"),
            "rating": result.get("rating"),
            "score": result.get("score"),
        }


job_queue_service = JobQueueService()
