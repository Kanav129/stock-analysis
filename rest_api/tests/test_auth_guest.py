"""Guest auth: public guest login, read-only desk, stripped personal fields."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from rest_api.guest_privacy import sanitize_guest_holdings_payload
from rest_api.main import app

ADMIN_KEY = "test-admin-secret"
client = TestClient(app)

SAMPLE_HOLDING = {
    "account_id": "U123",
    "ticker": "AAPL",
    "quantity": 10.0,
    "avg_cost": 150.0,
    "market_price": 200.0,
    "market_value": 2000.0,
    "unrealized_pnl": 500.0,
    "currency": "USD",
    "snapshot_at": "2026-08-19T00:00:00+00:00",
    "asset_class": "STK",
    "description": "APPLE INC",
    "ibkr_mark_price": 199.5,
    "ibkr_position_value": 1995.0,
    "cost_basis_money": 1500.0,
    "cost_basis_price": 150.0,
    "ibkr_unrealized_pnl": 495.0,
    "percent_of_nav": 12.5,
    "source_data": {"qty": 10},
    "price_date": "2026-08-19",
}

SAMPLE_SUMMARY = {
    "total_value": 2000.0,
    "total_unrealized_pnl": 500.0,
    "day_change_pct": 1.2,
    "day_change_value": 24.0,
    "overall_change_pct": 33.3,
    "position_count": 1,
    "snapshot_at": "2026-08-19T00:00:00+00:00",
    "holdings_synced_at": "2026-08-19T12:00:00+00:00",
    "source": "ibkr_flex",
}


@pytest.fixture(autouse=True)
def require_admin_key(monkeypatch):
    monkeypatch.setattr("rest_api.auth._admin_key", lambda: ADMIN_KEY)


def _guest_headers() -> dict[str, str]:
    resp = client.post("/auth/guest")
    assert resp.status_code == 200
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {ADMIN_KEY}"}


def test_guest_login_returns_guest_role_and_token():
    resp = client.post("/auth/guest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["role"] == "guest"
    assert body["token"]
    assert body["auth_required"] is True


def test_admin_login_returns_admin_role():
    resp = client.post("/auth/login", json={"key": ADMIN_KEY})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["role"] == "admin"
    assert body["auth_required"] is True


def test_guest_cannot_run_analysis():
    resp = client.post("/analysis/run", json={}, headers=_guest_headers())
    assert resp.status_code == 403


def test_guest_cannot_sync_data():
    resp = client.post("/sync/data", json={}, headers=_guest_headers())
    assert resp.status_code == 403


def test_guest_cannot_mutate_watchlist():
    resp = client.post(
        "/watchlist",
        json={"ticker": "MSFT"},
        headers=_guest_headers(),
    )
    assert resp.status_code == 403


def test_guest_cannot_sync_holdings():
    resp = client.post("/holdings/sync", json={}, headers=_guest_headers())
    assert resp.status_code == 403


def test_guest_cannot_get_settings():
    resp = client.get("/settings", headers=_guest_headers())
    assert resp.status_code == 403


@patch("rest_api.routes.stock_routes.sync_service")
@patch("rest_api.routes.stock_routes.StockDataScraper")
def test_guest_can_live_refresh(mock_scraper_cls, mock_sync):
    from services.live_refresh_service import live_refresh_service

    live_refresh_service._pause_until = 0.0
    live_refresh_service._running = False
    mock_sync.is_running = False
    mock_scraper_cls.return_value.refresh_live_1m.return_value = 1
    resp = client.post(
        "/stock/prices/live-refresh",
        json={"tickers": ["SPY"]},
        headers=_guest_headers(),
    )
    assert resp.status_code not in (401, 403)
    assert resp.status_code == 200


def test_wrong_key_is_unauthorized():
    resp = client.get("/holdings", headers={"Authorization": "Bearer no-such-key"})
    assert resp.status_code == 401


def test_sanitize_guest_holdings_payload_strips_dollars():
    payload = {
        "holdings": [dict(SAMPLE_HOLDING)],
        "summary": dict(SAMPLE_SUMMARY),
        "holdings_synced_at": SAMPLE_SUMMARY["holdings_synced_at"],
        "source": "ibkr_flex",
    }
    out = sanitize_guest_holdings_payload(payload)
    row = out["holdings"][0]
    assert row["ticker"] == "AAPL"
    assert row["market_price"] == 200.0
    assert row["currency"] == "USD"
    assert row["description"] == "APPLE INC"
    assert row["asset_class"] == "STK"
    assert row["price_date"] == "2026-08-19"
    assert row["quantity"] is None
    assert row["avg_cost"] is None
    assert row["market_value"] is None
    assert row["unrealized_pnl"] is None
    assert row["percent_of_nav"] is None
    assert row["account_id"] is None
    assert row["ibkr_position_value"] is None
    assert row["cost_basis_money"] is None
    summary = out["summary"]
    assert summary["position_count"] == 1
    assert summary["total_value"] is None
    assert summary["total_unrealized_pnl"] is None
    assert summary["day_change_pct"] is None
    assert summary["day_change_value"] is None
    assert summary["overall_change_pct"] is None


@patch("rest_api.routes.holdings_routes.holdings_service")
def test_guest_get_holdings_omits_personal_fields(mock_holdings):
    mock_holdings.get_current_holdings.return_value = [dict(SAMPLE_HOLDING)]
    mock_holdings.portfolio_summary.return_value = dict(SAMPLE_SUMMARY)
    mock_holdings.sync_metadata.return_value = {
        "holdings_synced_at": SAMPLE_SUMMARY["holdings_synced_at"],
        "source": "ibkr_flex",
    }
    resp = client.get("/holdings", headers=_guest_headers())
    assert resp.status_code == 200
    row = resp.json()["holdings"][0]
    assert row["ticker"] == "AAPL"
    assert row["market_price"] == 200.0
    assert row["quantity"] is None
    assert row["market_value"] is None
    assert resp.json()["summary"]["total_value"] is None


@patch("rest_api.routes.holdings_routes.holdings_service")
def test_admin_get_holdings_keeps_personal_fields(mock_holdings):
    mock_holdings.get_current_holdings.return_value = [dict(SAMPLE_HOLDING)]
    mock_holdings.portfolio_summary.return_value = dict(SAMPLE_SUMMARY)
    mock_holdings.sync_metadata.return_value = {
        "holdings_synced_at": SAMPLE_SUMMARY["holdings_synced_at"],
        "source": "ibkr_flex",
    }
    resp = client.get("/holdings", headers=_admin_headers())
    assert resp.status_code == 200
    row = resp.json()["holdings"][0]
    assert row["quantity"] == 10.0
    assert row["market_value"] == 2000.0
    assert resp.json()["summary"]["total_value"] == 2000.0


@patch("rest_api.routes.desk_routes.desk_snapshot_service.get_snapshot")
def test_guest_desk_snapshot_omits_personal_fields(get_snap):
    get_snap.return_value = {
        "holdings": {
            "holdings": [dict(SAMPLE_HOLDING)],
            "summary": dict(SAMPLE_SUMMARY),
            "holdings_synced_at": SAMPLE_SUMMARY["holdings_synced_at"],
            "source": "ibkr_flex",
        },
        "watchlist": {"items": [{"ticker": "MSFT", "latest_price": 400.0}]},
        "ratings": {"ratings": []},
        "recent_ratings": {"ratings": []},
        "quotes": {"quotes": {}},
        "meta": {"desk_tickers": ["AAPL", "MSFT"], "market_tickers": []},
    }
    resp = client.get("/desk/snapshot", headers=_guest_headers())
    assert resp.status_code == 200
    body = resp.json()
    row = body["holdings"]["holdings"][0]
    assert row["ticker"] == "AAPL"
    assert row["market_price"] == 200.0
    assert row["quantity"] is None
    assert row["market_value"] is None
    assert body["holdings"]["summary"]["total_value"] is None
    assert body["watchlist"]["items"][0]["latest_price"] == 400.0
