from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rest_api.routes.watchlist_routes import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


@patch("rest_api.routes.watchlist_routes.suggestion_service.list_active")
def test_list_suggestions(mock_list):
    mock_list.return_value = [
        {
            "ticker": "AMD",
            "reason": "Chip demand headlines",
            "suggested_at": "2026-08-09T00:00:00+00:00",
            "expires_at": "2026-08-16T00:00:00+00:00",
            "source": "market",
        }
    ]
    response = client.get("/watchlist/suggestions")
    assert response.status_code == 200
    assert response.json()["items"][0]["ticker"] == "AMD"


@patch("rest_api.routes.watchlist_routes.suggestion_service.accept")
def test_accept_suggestion(mock_accept):
    mock_accept.return_value = {
        "ticker": "AMD",
        "item": {"ticker": "AMD", "notes": "Added from AI suggestion"},
        "job": {"started": True},
    }
    response = client.post("/watchlist/suggestions/accept", json={"ticker": "AMD"})
    assert response.status_code == 200
    assert response.json()["ticker"] == "AMD"
    mock_accept.assert_called_once_with("AMD")


@patch("rest_api.routes.watchlist_routes.suggestion_service.get")
def test_get_suggestion_detail(mock_get):
    mock_get.return_value = {
        "ticker": "AMD",
        "reason": "Chip demand headlines",
        "company_blurb": "Semiconductor designer",
        "brief": {"thesis": "Watch for AI GPU demand", "reasons": [], "sources": []},
    }
    response = client.get("/watchlist/suggestions/AMD")
    assert response.status_code == 200
    assert response.json()["brief"]["thesis"].startswith("Watch")


@patch("rest_api.routes.watchlist_routes.suggestion_service.get")
def test_get_suggestion_404(mock_get):
    mock_get.return_value = None
    response = client.get("/watchlist/suggestions/ZZZZ")
    assert response.status_code == 404
