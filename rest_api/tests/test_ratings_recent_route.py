from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rest_api.routes.analysis_routes import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


@patch("rest_api.routes.analysis_routes.ratings_service.get_recent_ratings")
def test_ratings_recent_route(mock_recent):
    mock_recent.return_value = [
        {
            "id": 1,
            "ticker": "AAPL",
            "rating": "BUY",
            "score": 42,
            "reasoning": "x",
            "key_drivers": [],
            "supporting_headlines": [],
            "price_summary": {},
            "created_at": "2026-08-01T12:00:00",
        }
    ]

    response = client.get("/ratings/recent?limit=8")

    assert response.status_code == 200
    assert response.json()["ratings"][0]["ticker"] == "AAPL"
    mock_recent.assert_called_once_with(8)


@patch("rest_api.routes.analysis_routes.ratings_service.get_rating_history")
def test_ratings_recent_does_not_collide_with_ticker_route(mock_history):
    mock_history.return_value = []
    response = client.get("/ratings/AAPL")
    assert response.status_code == 200
    mock_history.assert_called_once_with("AAPL")
