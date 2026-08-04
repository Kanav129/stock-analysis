from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rest_api.routes.analysis_routes import router


app = FastAPI()
app.include_router(router)
client = TestClient(app)


@patch("rest_api.routes.analysis_routes.job_queue_service.enqueue")
@patch(
    "rest_api.routes.analysis_routes.ratings_service.list_latest_failures"
)
def test_retry_failed_enqueues_core_and_deep_by_report_type(mock_list_failed, mock_enqueue):
    mock_list_failed.return_value = [
        {"ticker": "AAA", "report_type": "core"},
        {"ticker": "BBB", "report_type": "deep"},
        {"ticker": "CCC", "report_type": "core"},
    ]
    mock_enqueue.side_effect = [
        {"enqueued": [{"id": "1", "ticker": "AAA"}], "reused": []},
        {"enqueued": [{"id": "2", "ticker": "BBB"}], "reused": []},
    ]

    response = client.post("/analysis/retry-failed")

    assert response.status_code == 200
    body = response.json()
    assert body["tickers"] == ["AAA", "BBB", "CCC"]
    assert body["core"] == ["AAA", "CCC"]
    assert body["deep"] == ["BBB"]
    assert body["running"] is True
    assert mock_enqueue.call_count == 2
    mock_enqueue.assert_any_call("core_analysis", ["AAA", "CCC"], force=True)
    mock_enqueue.assert_any_call("deep_dive", ["BBB"], force=True)


@patch("rest_api.routes.analysis_routes.job_queue_service.enqueue")
@patch(
    "rest_api.routes.analysis_routes.ratings_service.list_latest_failures"
)
def test_retry_failed_returns_idle_when_no_failures(mock_list_failed, mock_enqueue):
    mock_list_failed.return_value = []

    response = client.post("/analysis/retry-failed")

    assert response.status_code == 200
    assert response.json() == {
        "tickers": [],
        "core": [],
        "deep": [],
        "message": "No failed analyses",
        "running": False,
    }
    mock_enqueue.assert_not_called()
