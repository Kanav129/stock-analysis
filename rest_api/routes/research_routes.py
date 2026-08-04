"""Research report API routes — enqueue via durable desk job queue."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from services.job_queue_service import JOB_CORE, JOB_DEEP, job_queue_service
from services.report_pdf_service import build_report_pdf
from services.report_service import ReportService, resolve_report_type_filter
from utils.logger import logger

router = APIRouter(prefix="/research", tags=["Research"])


class GenerateResponse(BaseModel):
    task_id: str
    status: str  # queued | running | pending


class TaskStatus(BaseModel):
    task_id: str
    status: str
    ticker: str
    report_type: str
    report_id: int | None = None
    rating: str | None = None
    score: int | None = None
    error: str | None = None


class ActiveTaskResponse(BaseModel):
    task: TaskStatus | None = None


_JOB_TO_REPORT = {JOB_CORE: "core", JOB_DEEP: "deep"}
_REPORT_TO_JOB = {"core": JOB_CORE, "deep": JOB_DEEP}


def _job_to_task_status(job: dict) -> TaskStatus:
    report_type = _JOB_TO_REPORT.get(job["job_type"], "core")
    status = job["status"]
    # Compat with older FE expecting pending
    if status == "queued":
        status = "pending"
    result = job.get("result") or {}
    return TaskStatus(
        task_id=job["id"],
        status=status,
        ticker=job["ticker"],
        report_type=report_type,
        report_id=result.get("report_id"),
        rating=result.get("rating"),
        score=result.get("score"),
        error=job.get("error"),
    )


def _enqueue_research(ticker: str, report_type: str) -> GenerateResponse:
    job_type = _REPORT_TO_JOB.get(report_type)
    if not job_type:
        raise HTTPException(400, detail="Invalid report type")
    ticker = ticker.upper()
    out = job_queue_service.enqueue(job_type, [ticker])
    jobs = out.get("jobs") or []
    if not jobs:
        # already completed today for core — still allow explicit research enqueue?
        # For single-ticker research, force past daily gate by enqueueing with force
        if report_type == "core" and out.get("reason") == "already_completed_today":
            out = job_queue_service.enqueue(job_type, [ticker], force=True)
            jobs = out.get("jobs") or []
        if not jobs:
            raise HTTPException(500, detail=out.get("message") or "Failed to enqueue")
    job = jobs[0]
    status = job["status"]
    if status == "queued":
        status = "pending"
    logger.info(
        "Research job %s for %s (%s) status=%s",
        job["id"][:8],
        ticker,
        report_type,
        status,
    )
    return GenerateResponse(task_id=job["id"], status=status)


@router.post("/{ticker}")
async def generate_report(ticker: str):
    """Enqueue a core research report. Returns a job/task ID for polling."""
    return _enqueue_research(ticker.upper(), "core")


@router.post("/{ticker}/deep")
async def generate_deep_report(ticker: str):
    """Enqueue a deep-dive report. Returns a job/task ID for polling."""
    return _enqueue_research(ticker.upper(), "deep")


@router.get("/task/{task_id}")
async def get_task_status(task_id: str):
    """Poll for report generation status (desk_jobs row)."""
    job = job_queue_service.get_job(task_id)
    if not job:
        raise HTTPException(404, detail="Task not found")
    return _job_to_task_status(job)


@router.get("/{ticker}/active")
async def get_active_task(ticker: str):
    """Return an in-flight report job for this ticker, if any."""
    ticker = ticker.upper()
    for job_type in (JOB_DEEP, JOB_CORE):
        job = job_queue_service.find_active(ticker, job_type)
        if job:
            return ActiveTaskResponse(task=_job_to_task_status(job))
    return ActiveTaskResponse(task=None)


@router.get("/{ticker}")
async def get_report(ticker: str, type: str = "latest"):
    """Get the most recent saved report for a ticker.

    ``type=latest`` (default): newest row by ``created_at`` of any report_type.
    ``type=core|deep``: newest row of that type only.

    Preferring deep over a newer core report left stock pages showing stale deep
    dives after weekly core analysis updated desk ratings — always use latest by
    time unless the client explicitly filters.
    """
    try:
        report_type = resolve_report_type_filter(type)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    svc = ReportService()
    envelope = svc.get_latest_report_envelope(ticker.upper(), report_type)
    if envelope["report"] is None and not envelope["analysis_failed"]:
        label = report_type or "saved"
        raise HTTPException(404, detail=f"No {label} report found for {ticker}")
    return envelope


@router.get("/{ticker}/history")
async def get_report_history(ticker: str):
    """Get report history for a ticker (newest first), including rating/score."""
    svc = ReportService()
    items = svc.get_report_history(ticker.upper())
    return {"ticker": ticker.upper(), "items": items}


@router.get("/{ticker}/reports/{report_id}/pdf")
async def download_report_pdf(ticker: str, report_id: int):
    """Download one saved report as a PDF attachment."""
    svc = ReportService()
    report = svc.get_report_by_id(ticker.upper(), report_id)
    if not report:
        raise HTTPException(404, detail=f"Report {report_id} not found for {ticker}")
    try:
        pdf_bytes = build_report_pdf(report)
    except Exception as exc:
        logger.error("PDF build failed for %s report %s: %s", ticker, report_id, exc)
        raise HTTPException(500, detail="Failed to build PDF") from exc
    filename = f"{ticker.upper()}_{report.get('report_type', 'report')}_{report_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
