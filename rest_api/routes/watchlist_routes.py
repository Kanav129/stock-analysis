from fastapi import APIRouter, HTTPException

from rest_api.schemas import WatchlistCreate
from services.universe_service import UniverseService
from services.watchlist_service import WatchlistService

router = APIRouter()
watchlist_service = WatchlistService()
universe_service = UniverseService()


@router.get("/universe")
def get_universe():
    return universe_service.get_universe_detail()


@router.get("/watchlist")
def list_watchlist():
    return {"items": watchlist_service.list_items()}


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
