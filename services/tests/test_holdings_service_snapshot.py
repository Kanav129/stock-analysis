from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from services.holdings_service import HoldingsService, Position


def _position(ticker: str, qty: float = 1.0, account: str = "U1") -> Position:
    return Position(
        ticker=ticker,
        quantity=qty,
        avg_cost=10.0,
        market_price=12.0,
        market_value=12.0 * qty,
        unrealized_pnl=2.0 * qty,
        account_id=account,
        source="ibkr_flex",
        ibkr_mark_price=12.0,
        ibkr_position_value=12.0 * qty,
        ibkr_unrealized_pnl=2.0 * qty,
        source_data={"symbol": ticker},
    )


@patch("services.holdings_service.execute_values")
@patch("services.holdings_service.get_db_client")
def test_replace_snapshot_writes_rows_and_meta(mock_get_db, mock_ev):
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = None
    db = MagicMock()
    db.checkout.return_value.__enter__.return_value = conn
    db.checkout.return_value.__exit__.return_value = None
    mock_get_db.return_value = db

    svc = HoldingsService()
    snap = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    meta = svc.replace_snapshot(
        [_position("AAPL"), _position("MSFT", account="U2")],
        snapshot_at=snap,
        source="ibkr_flex",
        skipped=1,
    )

    assert meta["saved"] == 2
    assert meta["skipped"] == 1
    assert set(meta["tickers"]) == {"AAPL", "MSFT"}
    assert meta["source"] == "ibkr_flex"
    mock_ev.assert_called_once()
    assert len(mock_ev.call_args.args[2]) == 2
    # Meta upsert always runs
    assert any(
        "app_settings" in str(c.args[0])
        for c in cursor.execute.call_args_list
    )
    conn.commit.assert_called_once()


@patch("services.holdings_service.get_db_client")
def test_replace_snapshot_empty_still_updates_meta(mock_get_db):
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = None
    db = MagicMock()
    db.checkout.return_value.__enter__.return_value = conn
    db.checkout.return_value.__exit__.return_value = None
    mock_get_db.return_value = db

    svc = HoldingsService()
    meta = svc.replace_snapshot([], source="ibkr_flex", skipped=0)

    assert meta["saved"] == 0
    assert meta["tickers"] == []
    # No execute_values for empty book — only app_settings upsert
    assert cursor.execute.called
    conn.commit.assert_called_once()


@patch("services.holdings_service.execute_values", side_effect=RuntimeError("db down"))
@patch("services.holdings_service.get_db_client")
def test_replace_snapshot_failure_rolls_back(mock_get_db, _mock_ev):
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = None
    db = MagicMock()
    db.checkout.return_value.__enter__.return_value = conn
    db.checkout.return_value.__exit__.return_value = None
    mock_get_db.return_value = db

    svc = HoldingsService()
    try:
        svc.replace_snapshot([_position("AAPL")])
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass
    conn.rollback.assert_called()


@patch.object(HoldingsService, "_latest_snapshot_time")
@patch.object(HoldingsService, "_latest_closes")
@patch("services.holdings_service.get_db_client")
def test_get_current_holdings_keeps_ibkr_and_recomputes_live(
    mock_get_db, mock_closes, mock_latest
):
    snap = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    mock_latest.return_value = snap
    mock_closes.return_value = {
        "AAPL": {"close": 200.0, "date": "2026-08-01T00:00:00"},
    }
    db = MagicMock()
    db.fetch_query.return_value = (
        [
            (
                "U1",
                "AAPL",
                10.0,
                150.0,
                190.0,  # stored market_price (IBKR seed)
                1900.0,
                400.0,
                "USD",
                snap,
                "265598",
                "STK",
                "APPLE",
                "NASDAQ",
                "Long",
                1.0,
                "20260801",
                190.0,  # ibkr_mark
                1900.0,
                1500.0,
                150.0,
                400.0,  # ibkr_unrealized
                12.5,
                1.0,
                "AAPL",
                "ibkr_flex",
                {"symbol": "AAPL"},
            )
        ],
        [
            "account_id",
            "ticker",
            "quantity",
            "avg_cost",
            "market_price",
            "market_value",
            "unrealized_pnl",
            "currency",
            "snapshot_at",
            "conid",
            "asset_class",
            "description",
            "exchange",
            "side",
            "multiplier",
            "report_date",
            "ibkr_mark_price",
            "ibkr_position_value",
            "cost_basis_money",
            "cost_basis_price",
            "ibkr_unrealized_pnl",
            "percent_of_nav",
            "fx_rate_to_base",
            "raw_symbol",
            "source",
            "source_data",
        ],
    )
    mock_get_db.return_value = db

    holdings = HoldingsService().get_current_holdings()
    assert len(holdings) == 1
    h = holdings[0]
    assert h["ibkr_mark_price"] == 190.0
    assert h["ibkr_unrealized_pnl"] == 400.0
    assert h["market_price"] == 200.0
    assert h["market_value"] == 2000.0
    assert h["unrealized_pnl"] == 500.0
