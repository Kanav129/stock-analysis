from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from rest_api.schemas import AnalysisRunRequest
from services.analysis_service import analysis_service
from services.job_queue_service import JOB_CORE, JOB_DEEP, job_queue_service
from services.ratings_service import RatingsService

router = APIRouter()
ratings_service = RatingsService()


@router.get("/ratings")
def get_latest_ratings(tickers: Optional[str] = Query(None)):
    """Latest rating per ticker. Optional comma-separated tickers scopes the query."""
    ticker_list = None
    if tickers:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    return {"ratings": ratings_service.get_latest_ratings(ticker_list)}


@router.get("/ratings/recent")
def get_recent_ratings(limit: int = Query(8, ge=1, le=50)):
    """Most recent rating rows across the desk (chronological, not one-per-ticker)."""
    return {"ratings": ratings_service.get_recent_ratings(limit)}


@router.get("/ratings/{ticker}")
def get_rating_history(ticker: str):
    history = ratings_service.get_rating_history(ticker)
    return {"ticker": ticker.upper(), "history": history}


@router.post("/analysis/run")
def run_analysis(body: Optional[AnalysisRunRequest] = None):
    """Start universe analysis in the background; poll GET /analysis/status for progress."""
    tickers = body.tickers if body else None
    try:
        return analysis_service.start(tickers, force=body.force if body else False)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/analysis/retry-failed")
def retry_failed_analysis():
    """Force a new analysis for every ticker whose latest attempt failed.

    Retries preserve report type: failed deep dives re-enqueue as deep_dive;
    failed core runs re-enqueue as core_analysis.
    """
    failures = ratings_service.list_latest_failures()
    if not failures:
        return {
            "tickers": [],
            "core": [],
            "deep": [],
            "message": "No failed analyses",
            "running": False,
        }

    core = [f["ticker"] for f in failures if f.get("report_type") != "deep"]
    deep = [f["ticker"] for f in failures if f.get("report_type") == "deep"]
    enqueued: list[dict] = []
    reused: list[dict] = []

    if core:
        out = job_queue_service.enqueue(JOB_CORE, core, force=True)
        enqueued.extend(out.get("enqueued") or [])
        reused.extend(out.get("reused") or [])
    if deep:
        out = job_queue_service.enqueue(JOB_DEEP, deep, force=True)
        enqueued.extend(out.get("enqueued") or [])
        reused.extend(out.get("reused") or [])

    tickers = [f["ticker"] for f in failures]
    return {
        "tickers": tickers,
        "core": core,
        "deep": deep,
        "enqueued": enqueued,
        "reused": reused,
        "running": bool(enqueued or reused),
        "status": "running" if (enqueued or reused) else "idle",
    }


@router.post("/analysis/rescore")
def rescore_analysis(body: Optional[AnalysisRunRequest] = None):
    """Re-score ratings from saved report sections only (no data re-gather)."""
    tickers = body.tickers if body else None
    try:
        return analysis_service.start_rescore(tickers)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/analysis/cancel")
def cancel_analysis():
    return analysis_service.request_cancel()


@router.get("/analysis/status")
def analysis_status():
    return analysis_service.get_status()
