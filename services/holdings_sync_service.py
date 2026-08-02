"""Sync IBKR Flex Open Positions into holdings_snapshot."""
from __future__ import annotations

from typing import Any

from services.holdings_service import HoldingsService, Position
from services.ibkr_flex_service import (
    FlexConfigError,
    FlexParseResult,
    FlexPosition,
    FlexUpstreamError,
    IbkrFlexClient,
)
from utils.logger import logger


def _to_position(fp: FlexPosition) -> Position:
    return Position(
        ticker=fp.ticker,
        quantity=fp.quantity,
        avg_cost=fp.avg_cost,
        # Seed live desk marks from IBKR statement; GET /holdings overwrites from stock_data.
        market_price=fp.ibkr_mark_price,
        market_value=fp.ibkr_position_value,
        unrealized_pnl=fp.ibkr_unrealized_pnl,
        currency=fp.currency or "USD",
        account_id=fp.account_id or "default",
        conid=fp.conid,
        asset_class=fp.asset_class,
        description=fp.description,
        exchange=fp.exchange,
        side=fp.side,
        multiplier=fp.multiplier,
        report_date=fp.report_date,
        ibkr_mark_price=fp.ibkr_mark_price,
        ibkr_position_value=fp.ibkr_position_value,
        cost_basis_money=fp.cost_basis_money,
        cost_basis_price=fp.cost_basis_price,
        ibkr_unrealized_pnl=fp.ibkr_unrealized_pnl,
        percent_of_nav=fp.percent_of_nav,
        fx_rate_to_base=fp.fx_rate_to_base,
        raw_symbol=fp.raw_symbol,
        source="ibkr_flex",
        source_data=fp.source_data or {},
    )


class HoldingsSyncService:
    def __init__(
        self,
        *,
        flex_client: IbkrFlexClient | None = None,
        holdings_service: HoldingsService | None = None,
    ) -> None:
        self.flex = flex_client or IbkrFlexClient()
        self.holdings = holdings_service or HoldingsService()

    def sync_from_ibkr(self) -> dict[str, Any]:
        """Fetch Flex positions and atomically replace the current holdings book.

        Raises:
            FlexConfigError: missing IBKR_FLEX_TOKEN / IBKR_FLEX_QUERY_ID
            FlexUpstreamError: network, poll timeout, or parse failure

        On any raised error the prior snapshot is left untouched.
        """
        self.flex.ensure_configured()
        parsed: FlexParseResult = self.flex.download_positions()
        if parsed.skipped_asset_classes:
            logger.info(
                "Flex skipped non-equity asset classes: %s",
                parsed.skipped_asset_classes,
            )
        positions = [_to_position(p) for p in parsed.positions]
        meta = self.holdings.replace_snapshot(
            positions,
            source="ibkr_flex",
            skipped=parsed.skipped,
        )
        return {
            "saved": meta["saved"],
            "skipped": meta.get("skipped", parsed.skipped),
            "tickers": meta.get("tickers", []),
            "snapshot_at": meta.get("snapshot_at"),
            "source": "ibkr_flex",
            "skipped_asset_classes": parsed.skipped_asset_classes,
        }


holdings_sync_service = HoldingsSyncService()


__all__ = [
    "HoldingsSyncService",
    "holdings_sync_service",
    "FlexConfigError",
    "FlexUpstreamError",
]
