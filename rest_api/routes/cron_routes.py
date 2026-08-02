"""HTTP hooks for external schedulers (GitHub Actions, cron-job.org, etc.).

Protected by ADMIN_KEY via the global auth middleware — send:
  Authorization: Bearer <ADMIN_KEY>
"""

from fastapi import APIRouter, HTTPException

from services import run_checkpoint_service as rcs
from services.analysis_service import analysis_service
from services.holdings_sync_service import holdings_sync_service
from services.ibkr_flex_service import FlexConfigError, FlexUpstreamError
from services.sync_service import sync_service
from services.universe_service import UniverseService

router = APIRouter(prefix="/cron", tags=["Cron"])


def _sync_ready_for_analysis() -> tuple[bool, dict]:
    """True when today's sync checkpoint is complete for the full universe."""
    day = rcs.today_key()
    universe = [t.upper() for t in UniverseService().get_tickers()]
    checkpoint = rcs.load_sync(day)
    daily = rcs.daily_sync_summary(checkpoint, universe)
    return bool(daily.get("already_completed_today")), daily


@router.post("/holdings/sync")
def cron_holdings_sync():
    """Sync IBKR Flex holdings into the current snapshot (synchronous, bounded)."""
    try:
        return holdings_sync_service.sync_from_ibkr()
    except FlexConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except FlexUpstreamError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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

    Requires today's sync to be complete (unless already_completed_today for analysis).
    Uses force=False so a successful run earlier today is a no-op.
    """
    try:
        sync_ok, sync_daily = _sync_ready_for_analysis()
        if not sync_ok:
            return {
                "started": False,
                "reason": "sync_not_complete",
                "date": rcs.today_key(),
                "message": (
                    "Daily sync is not complete for today. Run POST /cron/sync first."
                ),
                "sync_daily": sync_daily,
                "running": False,
                "status": "idle",
            }
        return analysis_service.start(force=False)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
