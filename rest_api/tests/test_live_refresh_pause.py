from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from rest_api.main import app
from services.live_refresh_service import live_refresh_service

client = TestClient(app)


def setup_function():
    live_refresh_service._pause_until = 0.0
    live_refresh_service._running = False


@patch("rest_api.routes.stock_routes.sync_service")
@patch("rest_api.routes.stock_routes.StockDataScraper")
def test_live_refresh_pauses_on_yahoo_rate_limit(mock_scraper_cls, mock_sync):
    mock_sync.is_running = False
    scraper = MagicMock()
    scraper.refresh_live_1m.side_effect = Exception(
        "Too Many Requests. Rate limited. Try after a while."
    )
    mock_scraper_cls.return_value = scraper

    res = client.post("/stock/prices/live-refresh", json={"tickers": ["SPY", "QQQ"]})
    assert res.status_code == 200
    body = res.json()
    assert body["rate_limited"] is True
    assert body["pause_until"]
    assert "SPY" in body["results"]
    assert "QQQ" not in body["results"]
    scraper.refresh_live_1m.assert_called_once_with("SPY")
    assert live_refresh_service.is_paused()


@patch("rest_api.routes.stock_routes.sync_service")
def test_live_refresh_skips_while_paused(mock_sync):
    mock_sync.is_running = False
    live_refresh_service.record_rate_limit()

    res = client.post("/stock/prices/live-refresh", json={"tickers": ["SPY"]})
    assert res.status_code == 200
    body = res.json()
    assert body["skipped"] is True
    assert body["reason"] == "rate_limited"
    assert body["pause_until"]
