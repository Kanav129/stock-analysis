from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rest_api.routes.cron_routes import router
from services.ibkr_flex_service import FlexConfigError, FlexUpstreamError

app = FastAPI()
app.include_router(router)
client = TestClient(app)


@patch("rest_api.routes.cron_routes.analysis_service.start")
@patch("rest_api.routes.cron_routes._sync_ready_for_analysis")
def test_cron_analyze_starts_when_sync_complete(mock_sync_ready, mock_start):
    mock_sync_ready.return_value = (True, {"already_completed_today": True})
    mock_start.return_value = {"started": True, "status": "running"}

    response = client.post("/cron/analyze")

    assert response.status_code == 200
    assert response.json()["started"] is True
    mock_start.assert_called_once_with(force=False)


@patch("rest_api.routes.cron_routes.analysis_service.start")
@patch("rest_api.routes.cron_routes._sync_ready_for_analysis")
def test_cron_analyze_blocks_when_sync_incomplete(mock_sync_ready, mock_start):
    mock_sync_ready.return_value = (
        False,
        {"already_completed_today": False, "status": "partial"},
    )

    response = client.post("/cron/analyze")

    assert response.status_code == 200
    data = response.json()
    assert data["started"] is False
    assert data["reason"] == "sync_not_complete"
    mock_start.assert_not_called()


@patch("rest_api.routes.cron_routes.holdings_sync_service.sync_from_ibkr")
def test_cron_holdings_sync_success(mock_sync):
    mock_sync.return_value = {
        "saved": 1,
        "skipped": 0,
        "tickers": ["AAPL"],
        "snapshot_at": "2026-08-01T12:00:00+00:00",
        "source": "ibkr_flex",
    }
    response = client.post("/cron/holdings/sync")
    assert response.status_code == 200
    assert response.json()["saved"] == 1


@patch("rest_api.routes.cron_routes.holdings_sync_service.sync_from_ibkr")
def test_cron_holdings_sync_config_error(mock_sync):
    mock_sync.side_effect = FlexConfigError("not configured")
    response = client.post("/cron/holdings/sync")
    assert response.status_code == 503


@patch("rest_api.routes.cron_routes.holdings_sync_service.sync_from_ibkr")
def test_cron_holdings_sync_upstream_error(mock_sync):
    mock_sync.side_effect = FlexUpstreamError("upstream")
    response = client.post("/cron/holdings/sync")
    assert response.status_code == 502
