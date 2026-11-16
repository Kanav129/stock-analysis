"""GET /analysis/outcomes/directional returns the core directional card."""
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rest_api.routes.analysis_routes import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


@patch("services.outcome_service.outcome_service.directional_success")
def test_directional_route_returns_service_payload(mock_card):
    mock_card.return_value = {
        "scope": "core",
        "disclaimer": "Directional experiment. Not a performance promise.",
        "overall": {
            "5d": {"hit_rate": 0.5, "hits": 1, "n": 2},
            "20d": {"hit_rate": None, "hits": 0, "n": 0},
        },
        "week": {
            "status": "ready",
            "week_start": "2026-11-02",
            "week_end": "2026-11-08",
            "pending_week_start": None,
            "message": None,
            "rows": [
                {
                    "ticker": "AAPL",
                    "rating": "BUY",
                    "score": 48,
                    "rated_at": "2026-11-02T11:00:00+00:00",
                    "return_5d": 0.02,
                    "outcome": "hit",
                }
            ],
        },
    }

    response = client.get("/analysis/outcomes/directional")

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "core"
    assert body["overall"]["5d"]["n"] == 2
    assert body["week"]["rows"][0]["outcome"] == "hit"
    mock_card.assert_called_once_with()


@patch("services.outcome_service.outcome_service.refresh")
def test_refresh_route_can_regrade_holds_only(mock_refresh):
    mock_refresh.return_value = {
        "candidates": 2,
        "updated": 2,
        "skipped": 0,
        "snapshots": 3,
        "holds_only": True,
    }
    response = client.post("/analysis/outcomes/refresh?holds_only=true")
    assert response.status_code == 200
    assert response.json()["holds_only"] is True
    mock_refresh.assert_called_once_with(limit=None, holds_only=True)
