from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rest_api.routes.research_routes import router


app = FastAPI()
app.include_router(router)
client = TestClient(app)


@patch("rest_api.routes.research_routes.ReportService")
def test_get_report_returns_report_envelope(mock_report_service):
    envelope = {
        "report": {"id": 7, "ticker": "AAPL", "report_type": "core"},
        "analysis_failed": False,
        "analysis_error": None,
        "failed_at": None,
    }
    mock_report_service.return_value.get_latest_report_envelope.return_value = envelope

    response = client.get("/research/aapl", params={"type": "core"})

    assert response.status_code == 200
    assert response.json() == envelope
    mock_report_service.return_value.get_latest_report_envelope.assert_called_once_with(
        "AAPL", "core"
    )


@patch("rest_api.routes.research_routes.ReportService")
def test_get_report_returns_200_for_failed_analysis_without_report(mock_report_service):
    envelope = {
        "report": None,
        "analysis_failed": True,
        "analysis_error": "Model unavailable",
        "failed_at": "2026-08-04T12:00:00",
    }
    mock_report_service.return_value.get_latest_report_envelope.return_value = envelope

    response = client.get("/research/aapl")

    assert response.status_code == 200
    assert response.json() == envelope


@patch("rest_api.routes.research_routes.ReportService")
def test_get_report_returns_404_when_no_report_or_failed_analysis(mock_report_service):
    mock_report_service.return_value.get_latest_report_envelope.return_value = {
        "report": None,
        "analysis_failed": False,
        "analysis_error": None,
        "failed_at": None,
    }

    response = client.get("/research/aapl")

    assert response.status_code == 404
    assert response.json() == {"detail": "No saved report found for aapl"}
