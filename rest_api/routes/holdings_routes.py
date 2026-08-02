from fastapi import APIRouter, HTTPException

from services.holdings_service import HoldingsService
from services.holdings_sync_service import holdings_sync_service
from services.ibkr_flex_service import FlexConfigError, FlexUpstreamError

router = APIRouter()
holdings_service = HoldingsService()


@router.get("/holdings")
def get_holdings():
    """Return persisted holdings snapshots (prices recomputed from synced stock_data)."""
    holdings = holdings_service.get_current_holdings()
    summary = holdings_service.portfolio_summary()
    meta = holdings_service.sync_metadata()
    return {
        "holdings": holdings,
        "summary": summary,
        "holdings_synced_at": meta.get("holdings_synced_at"),
        "source": meta.get("source"),
    }


@router.post("/holdings/sync")
def sync_holdings():
    """Pull Open Positions from IBKR Flex and replace the current holdings snapshot."""
    try:
        result = holdings_sync_service.sync_from_ibkr()
    except FlexConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except FlexUpstreamError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return result
