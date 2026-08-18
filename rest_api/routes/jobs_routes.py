"""Unified desk job queue API (LLM jobs + sync snapshot)."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from services.analysis_service import analysis_service
from services.job_queue_service import (
    JOB_CORE,
    JOB_DEEP,
    JOB_RESCORE,
    job_queue_service,
)
from services.sync_service import sync_service
from services.universe_service import UniverseService

router = APIRouter(prefix="/jobs", tags=["Jobs"])

_VALID_TYPES = {JOB_CORE, JOB_DEEP, JOB_RESCORE}


class EnqueueJobsRequest(BaseModel):
    job_type: str = Field(..., description="core_analysis | deep_dive | rescore")
    tickers: Optional[List[str]] = None
    force: bool = False


@router.get("")
def list_jobs(lite: bool = Query(False, description="Skip heavy analysis status (idle polls)")):
    """Active + recent LLM jobs, sync snapshot, optional analysis, concurrency limits."""
    job_queue_service.ensure_started()
    jobs = job_queue_service.list_jobs()
    sync_status = sync_service.get_status()
    sync_payload = None
    sync_st = sync_status.get("status")
    if sync_status.get("running") or sync_st in (
        "running",
        "cancelled",
        "completed",
        "error",
        "partial",
    ):
        # Include sync when active or recently finished (UI hides idle)
        if sync_status.get("running") or sync_st == "running":
            sync_payload = sync_status
        elif sync_status.get("finished_at"):
            sync_payload = sync_status

    payload = {
        "sync": sync_payload,
        "jobs": jobs,
        "limits": job_queue_service.limits(),
        "duration_estimates": job_queue_service.duration_estimates(),
    }
    # Full analysis status hits universe/DB — omit on idle lite polls.
    # Still include when work is active so clients can promote lite→full.
    has_active = any(
        isinstance(j, dict) and j.get("status") in ("queued", "running") for j in jobs
    ) or bool(sync_payload and (sync_payload.get("running") or sync_st == "running"))
    if not lite or has_active:
        payload["analysis"] = analysis_service.get_status()
    return payload


@router.post("")
def enqueue_jobs(body: EnqueueJobsRequest):
    job_type = (body.job_type or "").strip()
    if job_type not in _VALID_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"job_type must be one of {sorted(_VALID_TYPES)}",
        )
    tickers = body.tickers
    if not tickers:
        if job_type == JOB_CORE:
            tickers = UniverseService().get_tickers()
        else:
            raise HTTPException(status_code=400, detail="tickers required")
    try:
        return job_queue_service.enqueue(job_type, tickers, force=body.force)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/cancel-all")
def cancel_all_jobs():
    return job_queue_service.cancel_all()


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str):
    out = job_queue_service.cancel(job_id)
    if out.get("error") == "not_found":
        raise HTTPException(status_code=404, detail="Job not found")
    return out
