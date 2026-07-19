"""HTTP hooks for external schedulers (GitHub Actions, cron-job.org, etc.).

Protected by ADMIN_KEY via the global auth middleware — send:
  Authorization: Bearer <ADMIN_KEY>
"""

from fastapi import APIRouter, HTTPException

from services.analysis_service import analysis_service
from services.sync_service import sync_service

router = APIRouter(prefix="/cron", tags=["Cron"])


@router.post("/sync")
async def cron_sync():
    """Scrape prices + news for the universe (daily job)."""
    try:
        return await sync_service.sync_data()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/analyze")
def cron_analyze():
    """Start weekly core-report analysis in the background; poll /analysis/status."""
    try:
        return analysis_service.start()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
