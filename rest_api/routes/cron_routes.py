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
    """Start daily price+news sync in the background; poll GET /sync/status.

    Uses force=False so a successful sync earlier today is a no-op (already_completed_today).
    """
    try:
        return sync_service.start(force=False)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/analyze")
def cron_analyze():
    """Start weekly core-report analysis in the background; poll GET /analysis/status.

    Uses force=False so a successful run earlier today is a no-op (already_completed_today).
    """
    try:
        return analysis_service.start(force=False)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
