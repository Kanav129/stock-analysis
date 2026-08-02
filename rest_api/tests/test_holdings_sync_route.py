from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rest_api.routes.holdings_routes import router
from services.ibkr_flex_service import FlexConfigError, FlexUpstreamError

app = FastAPI()
app.include_router(router)
client = TestClient(app)


@patch("rest_api.routes.holdings_routes.holdings_sync_service.sync_from_ibkr")
def test_holdings_sync_success(mock_sync):
    mock_sync.return_value = {
        "saved": 2,
        "skipped": 1,
        "tickers": ["AAPL", "SPY"],
        "snapshot_at": "2026-08-01T12:00:00+00:00",
        "source": "ibkr_flex",
    }
    response = client.post("/holdings/sync")
    assert response.status_code == 200
    assert response.json()["saved"] == 2
    assert response.json()["source"] == "ibkr_flex"


@patch("rest_api.routes.holdings_routes.holdings_sync_service.sync_from_ibkr")
def test_holdings_sync_missing_config(mock_sync):
    mock_sync.side_effect = FlexConfigError("IBKR Flex is not configured")
    response = client.post("/holdings/sync")
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


@patch("rest_api.routes.holdings_routes.holdings_sync_service.sync_from_ibkr")
def test_holdings_sync_upstream_failure(mock_sync):
    mock_sync.side_effect = FlexUpstreamError("Flex statement not ready")
    response = client.post("/holdings/sync")
    assert response.status_code == 502
    assert "not ready" in response.json()["detail"]
