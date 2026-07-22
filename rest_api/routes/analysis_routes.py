from typing import Optional

from fastapi import APIRouter, HTTPException

from rest_api.schemas import AnalysisRunRequest
from services.analysis_service import analysis_service
from services.ratings_service import RatingsService

router = APIRouter()
ratings_service = RatingsService()


@router.get("/ratings")
def get_latest_ratings():
    return {"ratings": ratings_service.get_latest_ratings()}


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
