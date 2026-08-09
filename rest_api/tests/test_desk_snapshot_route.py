"""Smoke test for GET /desk/snapshot."""
from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rest_api.routes.desk_routes import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


def test_desk_snapshot_route():
    payload = {
        "holdings": {"holdings": [], "summary": {"position_count": 0}},
        "watchlist": {"items": []},
        "ratings": {"ratings": []},
        "recent_ratings": {"ratings": []},
        "quotes": {"quotes": {"SPY": {"ticker": "SPY", "latest_close": 500}}},
        "meta": {
            "desk_tickers": [],
            "market_tickers": ["SPY", "QQQ", "IWM", "DIA"],
            "spark_days": 7,
            "recent_limit": 8,
        },
    }
    with patch(
        "rest_api.routes.desk_routes.desk_snapshot_service.get_snapshot",
        return_value=payload,
    ) as get_snap:
        resp = client.get("/desk/snapshot")
    assert resp.status_code == 200
    body = resp.json()
    assert body["quotes"]["quotes"]["SPY"]["latest_close"] == 500
    assert body["meta"]["spark_days"] == 7
    get_snap.assert_called_once()
