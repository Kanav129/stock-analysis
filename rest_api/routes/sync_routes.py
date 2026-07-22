from typing import Optional

from fastapi import APIRouter, HTTPException

from rest_api.schemas import SyncDataRequest
from services.sync_service import sync_service

router = APIRouter()


@router.post("/sync/data")
async def sync_data(body: Optional[SyncDataRequest] = None):
    """Start sync in the background; poll GET /sync/status until running=false."""
    tickers = body.tickers if body else None
    force = body.force if body else False
    try:
        return sync_service.start(tickers, force=force)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/sync/status")
def sync_status():
    return sync_service.get_status()
