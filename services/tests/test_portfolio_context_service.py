from unittest.mock import MagicMock, patch

from services.portfolio_context_service import build_portfolio_context


def test_empty_holdings_markdown():
    with patch(
        "services.portfolio_context_service.HoldingsService"
    ) as cls:
        cls.return_value.get_current_holdings.return_value = []
        out = build_portfolio_context("AAPL")
    assert out["has_holdings"] is False
    assert out["position_count"] == 0
    assert "no holdings" in out["markdown"].lower()
    assert "AAPL" in out["markdown"]
    assert out["current"]["held"] is False


def test_weights_and_current_highlight():
    holdings = [
        {
            "ticker": "AAPL",
            "quantity": 10,
            "market_value": 2000.0,
            "avg_cost": 150.0,
            "unrealized_pnl": 500.0,
        },
        {
            "ticker": "MSFT",
            "quantity": 5,
            "market_value": 3000.0,
            "avg_cost": 400.0,
            "unrealized_pnl": 1000.0,
        },
    ]
    with patch(
        "services.portfolio_context_service.HoldingsService"
    ) as cls:
        cls.return_value.get_current_holdings.return_value = holdings
        out = build_portfolio_context("aapl")

    assert out["has_holdings"] is True
    assert out["total_value"] == 5000.0
    assert out["position_count"] == 2
    assert out["current"]["held"] is True
    assert out["current"]["weight_pct"] == 40.0
    weights = {p["ticker"]: p["weight_pct"] for p in out["positions"]}
    assert weights["AAPL"] == 40.0
    assert weights["MSFT"] == 60.0
    assert abs(sum(weights.values()) - 100.0) < 0.01
    assert "Personal Portfolio" in out["markdown"]
    assert "AAPL" in out["markdown"] and "MSFT" in out["markdown"]
    assert "40" in out["markdown"]


def test_watchlist_only_ticker_not_held():
    holdings = [
        {
            "ticker": "MSFT",
            "quantity": 5,
            "market_value": 3000.0,
            "avg_cost": 400.0,
            "unrealized_pnl": 0.0,
        },
    ]
    with patch(
        "services.portfolio_context_service.HoldingsService"
    ) as cls:
        cls.return_value.get_current_holdings.return_value = holdings
        out = build_portfolio_context("NVDA")
    assert out["current"]["held"] is False
    assert out["current"]["ticker"] == "NVDA"
    assert "not held" in out["markdown"].lower()


def test_skips_rows_without_market_value():
    holdings = [
        {"ticker": "AAPL", "quantity": 1, "market_value": None, "avg_cost": 1},
        {"ticker": "MSFT", "quantity": 1, "market_value": 100.0, "avg_cost": 1},
    ]
    with patch(
        "services.portfolio_context_service.HoldingsService"
    ) as cls:
        cls.return_value.get_current_holdings.return_value = holdings
        out = build_portfolio_context("MSFT")
    assert out["total_value"] == 100.0
    assert len(out["positions"]) == 1
    assert out["positions"][0]["ticker"] == "MSFT"
