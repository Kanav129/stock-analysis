from unittest.mock import MagicMock

import pytest

from services.holdings_sync_service import HoldingsSyncService
from services.ibkr_flex_service import (
    FlexConfigError,
    FlexParseResult,
    FlexPosition,
    FlexUpstreamError,
)


def _flex_pos(ticker: str = "AAPL") -> FlexPosition:
    return FlexPosition(
        ticker=ticker,
        quantity=10,
        avg_cost=150,
        account_id="U123",
        currency="USD",
        conid="1",
        asset_class="STK",
        ibkr_mark_price=190,
        ibkr_position_value=1900,
        cost_basis_money=1500,
        cost_basis_price=150,
        ibkr_unrealized_pnl=400,
        percent_of_nav=12.5,
        raw_symbol=ticker,
        source_data={"symbol": ticker},
    )


def test_sync_maps_and_persists():
    flex = MagicMock()
    flex.ensure_configured.return_value = None
    flex.download_positions.return_value = FlexParseResult(
        positions=[_flex_pos("AAPL"), _flex_pos("SPY")],
        skipped=1,
        skipped_asset_classes={"OPT": 1},
    )
    holdings = MagicMock()
    holdings.replace_snapshot.return_value = {
        "saved": 2,
        "skipped": 1,
        "tickers": ["AAPL", "SPY"],
        "snapshot_at": "2026-08-01T12:00:00+00:00",
        "source": "ibkr_flex",
    }

    result = HoldingsSyncService(flex_client=flex, holdings_service=holdings).sync_from_ibkr()

    assert result["saved"] == 2
    assert result["skipped"] == 1
    assert result["source"] == "ibkr_flex"
    assert "AAPL" in result["tickers"]
    holdings.replace_snapshot.assert_called_once()
    args, kwargs = holdings.replace_snapshot.call_args
    assert len(args[0]) == 2
    assert args[0][0].ibkr_mark_price == 190
    assert args[0][0].source == "ibkr_flex"
    assert kwargs["source"] == "ibkr_flex"


def test_sync_empty_valid_report_clears_book():
    flex = MagicMock()
    flex.ensure_configured.return_value = None
    flex.download_positions.return_value = FlexParseResult(positions=[], skipped=0)
    holdings = MagicMock()
    holdings.replace_snapshot.return_value = {
        "saved": 0,
        "skipped": 0,
        "tickers": [],
        "snapshot_at": "2026-08-01T12:00:00+00:00",
        "source": "ibkr_flex",
    }

    result = HoldingsSyncService(flex_client=flex, holdings_service=holdings).sync_from_ibkr()
    assert result["saved"] == 0
    holdings.replace_snapshot.assert_called_once()


def test_sync_config_error_does_not_persist():
    flex = MagicMock()
    flex.ensure_configured.side_effect = FlexConfigError("not configured")
    holdings = MagicMock()

    with pytest.raises(FlexConfigError):
        HoldingsSyncService(flex_client=flex, holdings_service=holdings).sync_from_ibkr()
    holdings.replace_snapshot.assert_not_called()


def test_sync_upstream_error_does_not_persist():
    flex = MagicMock()
    flex.ensure_configured.return_value = None
    flex.download_positions.side_effect = FlexUpstreamError("timeout")
    holdings = MagicMock()

    with pytest.raises(FlexUpstreamError):
        HoldingsSyncService(flex_client=flex, holdings_service=holdings).sync_from_ibkr()
    holdings.replace_snapshot.assert_not_called()
