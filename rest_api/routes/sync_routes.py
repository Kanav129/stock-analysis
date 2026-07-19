from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.sync_service import sync_service

router = APIRouter()


class SyncDataRequest(BaseModel):
    tickers: Optional[list[str]] = None


@router.post("/sync/data")
async def sync_data(body: Optional[SyncDataRequest] = None):
    tickers = body.tickers if body else None
    try:
        return await sync_service.sync_data(tickers)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/sync/status")
def sync_status():
    last = sync_service.last_sync
    return {
        "last_sync": last.isoformat() if last else None,
        "running": sync_service.is_running,
    }
