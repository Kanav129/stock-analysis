from fastapi import APIRouter

from services.holdings_service import HoldingsService

router = APIRouter()
holdings_service = HoldingsService()


@router.get("/holdings")
def get_holdings():
    """Return persisted holdings snapshots (prices recomputed from synced stock_data)."""
    holdings = holdings_service.get_current_holdings()
    summary = holdings_service.portfolio_summary()
    return {"holdings": holdings, "summary": summary}
