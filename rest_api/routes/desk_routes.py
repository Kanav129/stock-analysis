"""Desk bootstrap endpoints."""
from fastapi import APIRouter

from services.desk_snapshot_service import desk_snapshot_service

router = APIRouter(prefix="/desk", tags=["Desk"])


@router.get("/snapshot")
def get_desk_snapshot():
    """Holdings, watchlist, ratings, and quotes for Trading Desk first paint."""
    return desk_snapshot_service.get_snapshot()
