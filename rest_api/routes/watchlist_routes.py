from fastapi import APIRouter, HTTPException

from rest_api.schemas import WatchlistCreate, WatchlistSuggestionAccept
from services.suggestion_service import SuggestionService
from services.universe_service import UniverseService
from services.watchlist_service import WatchlistService

router = APIRouter()
watchlist_service = WatchlistService()
universe_service = UniverseService()
suggestion_service = SuggestionService()


@router.get("/universe")
def get_universe():
    return universe_service.get_universe_detail()


@router.get("/watchlist")
def list_watchlist():
    return {"items": watchlist_service.list_items()}


@router.get("/watchlist/suggestions")
def list_watchlist_suggestions():
    return {"items": suggestion_service.list_active()}


@router.get("/watchlist/suggestions/{ticker}")
def get_watchlist_suggestion(ticker: str):
    item = suggestion_service.get(ticker)
    if not item:
        raise HTTPException(status_code=404, detail="Suggestion not found or expired")
    return item


@router.post("/watchlist/suggestions/accept")
def accept_watchlist_suggestion(body: WatchlistSuggestionAccept):
    try:
        return suggestion_service.accept(body.ticker)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/watchlist")
def add_to_watchlist(body: WatchlistCreate):
    try:
        item = watchlist_service.add(body.ticker, body.notes)
        return item
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/watchlist/{ticker}")
def remove_from_watchlist(ticker: str):
    watchlist_service.remove(ticker)
    return {"removed": ticker.upper()}
