"""Research report API routes."""
from __future__ import annotations

import json
import traceback
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from db.db_factory import get_db_client
from rag_graphs.research_graph.graph import run_research_graph
from services.report_service import ReportService
from utils.logger import logger

router = APIRouter(prefix="/research", tags=["Research"])

# In-memory task registry (for async report generation)
_task_registry: dict[str, dict] = {}
_ACTIVE_STATUSES = frozenset({"pending", "running"})


class GenerateResponse(BaseModel):
    task_id: str
    status: str  # "pending"


class TaskStatus(BaseModel):
    task_id: str
    status: str  # "pending" | "running" | "done" | "failed"
    ticker: str
    report_type: str
    report_id: int | None = None
    rating: str | None = None
    score: int | None = None
    error: str | None = None


class ActiveTaskResponse(BaseModel):
    task: TaskStatus | None = None


def _settings_key(task_id: str) -> str:
    return f"research_task:{task_id}"


def _persist_task(task_id: str, task: dict) -> None:
    """Mirror task state to app_settings so status survives reloads/navigation."""
    try:
        db = get_db_client()
        payload = json.dumps({"task_id": task_id, **task})
        db.execute_query(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """,
            (_settings_key(task_id), payload),
        )
    except Exception as exc:
        logger.warning(f"Failed to persist research task {task_id}: {exc}")


def _load_persisted_task(task_id: str) -> dict | None:
    try:
        db = get_db_client()
        rows, _ = db.fetch_query(
            "SELECT value FROM app_settings WHERE key = %s",
            (_settings_key(task_id),),
        )
        if not rows:
            return None
        data = json.loads(rows[0][0])
        data.pop("task_id", None)
        return data
    except Exception as exc:
        logger.warning(f"Failed to load research task {task_id}: {exc}")
        return None


def _clear_persisted_task(task_id: str) -> None:
    try:
        db = get_db_client()
        db.execute_query("DELETE FROM app_settings WHERE key = %s", (_settings_key(task_id),))
    except Exception as exc:
        logger.warning(f"Failed to clear research task {task_id}: {exc}")


def _find_persisted_active(ticker: str, report_type: str | None = None) -> tuple[str, dict] | None:
    ticker = ticker.upper()
    try:
        db = get_db_client()
        rows, _ = db.fetch_query(
            "SELECT key, value FROM app_settings WHERE key LIKE %s ORDER BY updated_at ASC",
            ("research_task:%",),
        )
    except Exception as exc:
        logger.warning(f"Failed to scan research tasks: {exc}")
        return None

    match: tuple[str, dict] | None = None
    for key, value in rows:
        try:
            data = json.loads(value)
        except json.JSONDecodeError:
            continue
        task_id = data.get("task_id") or key.split(":", 1)[-1]
        if data.get("ticker") != ticker:
            continue
        if data.get("status") not in _ACTIVE_STATUSES:
            continue
        if report_type and data.get("report_type") != report_type:
            continue
        task = {k: v for k, v in data.items() if k != "task_id"}
        _task_registry.setdefault(task_id, task)
        match = (task_id, _task_registry[task_id])
    return match


def _task_to_status(task_id: str, task: dict) -> TaskStatus:
    return TaskStatus(
        task_id=task_id,
        status=task["status"],
        ticker=task["ticker"],
        report_type=task["report_type"],
        report_id=task.get("report_id"),
        rating=task.get("rating"),
        score=task.get("score"),
        error=task.get("error"),
    )


def _get_task(task_id: str) -> dict | None:
    task = _task_registry.get(task_id)
    if task:
        return task
    loaded = _load_persisted_task(task_id)
    if loaded:
        _task_registry[task_id] = loaded
        return loaded
    return None


def _find_active_task(ticker: str, report_type: str | None = None) -> tuple[str, dict] | None:
    """Return the most recently registered pending/running task for a ticker."""
    ticker = ticker.upper()
    matches: list[tuple[str, dict]] = []
    for task_id, task in _task_registry.items():
        if task.get("ticker") != ticker:
            continue
        if task.get("status") not in _ACTIVE_STATUSES:
            continue
        if report_type and task.get("report_type") != report_type:
            continue
        matches.append((task_id, task))
    if matches:
        return matches[-1]
    return _find_persisted_active(ticker, report_type)


def _start_or_reuse_task(
    ticker: str,
    report_type: str,
    background_tasks: BackgroundTasks,
) -> GenerateResponse:
    existing = _find_active_task(ticker, report_type)
    if existing:
        task_id, task = existing
        logger.info(f"Research task {task_id} reused for {ticker} ({report_type})")
        return GenerateResponse(task_id=task_id, status=task["status"])

    task_id = str(uuid4())[:12]
    task = {
        "status": "pending",
        "ticker": ticker.upper(),
        "report_type": report_type,
        "report_id": None,
        "rating": None,
        "score": None,
        "error": None,
    }
    _task_registry[task_id] = task
    _persist_task(task_id, task)
    background_tasks.add_task(_run_report_task, task_id, ticker.upper(), report_type)
    logger.info(f"Research task {task_id} created for {ticker} ({report_type})")
    return GenerateResponse(task_id=task_id, status="pending")


@router.post("/{ticker}")
async def generate_report(ticker: str, background_tasks: BackgroundTasks):
    """Generate a core-4 research report for a ticker. Returns a task ID for polling."""
    return _start_or_reuse_task(ticker.upper(), "core", background_tasks)


@router.post("/{ticker}/deep")
async def generate_deep_report(ticker: str, background_tasks: BackgroundTasks):
    """Generate a deep-dive (all 8 analysts + debate) report. Returns a task ID for polling."""
    return _start_or_reuse_task(ticker.upper(), "deep", background_tasks)


@router.get("/task/{task_id}")
async def get_task_status(task_id: str):
    """Poll for report generation status. Returns the report when done."""
    task = _get_task(task_id)
    if not task:
        raise HTTPException(404, detail="Task not found")
    return _task_to_status(task_id, task)


@router.get("/{ticker}/active")
async def get_active_task(ticker: str):
    """Return an in-flight report task for this ticker, if any (survives page navigation)."""
    found = _find_active_task(ticker.upper())
    if not found:
        return ActiveTaskResponse(task=None)
    task_id, task = found
    return ActiveTaskResponse(task=_task_to_status(task_id, task))


@router.get("/{ticker}")
async def get_report(ticker: str, type: str = "core"):
    """Get the latest saved report for a ticker."""
    svc = ReportService()
    report = svc.get_latest_report(ticker.upper(), type)
    if not report:
        raise HTTPException(404, detail=f"No {type} report found for {ticker}")
    return report


@router.get("/{ticker}/history")
async def get_report_history(ticker: str):
    """Get all report timestamps for a ticker."""
    svc = ReportService()
    items = svc.get_report_history(ticker.upper())
    return {"ticker": ticker.upper(), "items": items}


def _run_report_task(task_id: str, ticker: str, report_type: str) -> None:
    """Background task: run the LangGraph research pipeline."""
    registry = _get_task(task_id)
    if not registry:
        return

    registry["status"] = "running"
    _persist_task(task_id, registry)
    try:
        result = run_research_graph(ticker, report_type)
        registry["status"] = "done"
        registry["report_id"] = result.get("report_id")
        registry["rating"] = result.get("rating")
        registry["score"] = result.get("score")
        _persist_task(task_id, registry)
        logger.info(f"Research task {task_id} completed: {ticker} {report_type} "
                     f"rating={result.get('rating')}")
    except Exception as exc:
        logger.error(f"Research task {task_id} failed: {exc}\n{traceback.format_exc()}")
        registry["status"] = "failed"
        registry["error"] = str(exc)
        _persist_task(task_id, registry)
