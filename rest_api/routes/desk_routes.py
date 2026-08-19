"""Desk bootstrap endpoints."""
from fastapi import APIRouter, Request

from rest_api.auth import get_auth_role
from rest_api.guest_privacy import sanitize_guest_desk_snapshot
from services.desk_snapshot_service import desk_snapshot_service

router = APIRouter(prefix="/desk", tags=["Desk"])


@router.get("/snapshot")
def get_desk_snapshot(request: Request):
    """Holdings, watchlist, ratings, and quotes for Trading Desk first paint."""
    snap = desk_snapshot_service.get_snapshot()
    if get_auth_role(request) == "guest":
        return sanitize_guest_desk_snapshot(snap)
    return snap
