from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.sync_service import sync_service

router = APIRouter()


class SyncDataRequest(BaseModel):
    tickers: Optional[list[str]] = None


@router.post("/sync/data")
async def sync_data(body: Optional[SyncDataRequest] = None):
    """Start sync in the background; poll GET /sync/status until running=false."""
    tickers = body.tickers if body else None
    try:
        return sync_service.start(tickers)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/sync/status")
def sync_status():
    return sync_service.get_status()
