"""ReportService envelopes preserve the last successful report."""
from unittest.mock import MagicMock, patch

from services.report_service import ReportService


REPORT_COLUMNS = [
    "id",
    "ticker",
    "report_type",
    "sections",
    "rating",
    "factor_scores",
    "entry_levels",
    "live_price",
    "model",
    "created_at",
]


def _row(
    report_id: int,
    created_at: str,
    rating: str,
) -> tuple:
    return (
        report_id,
        "AAPL",
        "core",
        "{}",
        rating,
        None,
        None,
        190.0,
        "test-model",
        created_at,
    )


@patch("services.report_service.get_db_client")
def test_latest_report_envelope_returns_success_without_failure_metadata(mock_db):
    db = MagicMock()
    db.fetch_query.return_value = (
        [_row(1, "2026-08-04T10:00:00", '{"rating":"BUY","score":20}')],
        REPORT_COLUMNS,
    )
    mock_db.return_value = db

    envelope = ReportService().get_latest_report_envelope("aapl", "core")

    assert envelope["report"]["id"] == 1
    assert envelope["analysis_failed"] is False
    assert envelope["analysis_error"] is None
    assert envelope["failed_at"] is None
    assert db.fetch_query.call_count == 1


@patch("services.report_service.get_db_client")
def test_latest_report_envelope_keeps_success_when_newer_analysis_failed(mock_db):
    db = MagicMock()
    db.fetch_query.side_effect = [
        (
            [
                _row(
                    2,
                    "2026-08-04T11:00:00",
                    '{"decision_ok":false,"error":"Decision model unavailable"}',
                )
            ],
            REPORT_COLUMNS,
        ),
        (
            [_row(1, "2026-08-04T10:00:00", '{"rating":"BUY","score":20}')],
            REPORT_COLUMNS,
        ),
    ]
    mock_db.return_value = db

    envelope = ReportService().get_latest_report_envelope("aapl", "core")

    assert envelope["report"]["id"] == 1
    assert envelope["analysis_failed"] is True
    assert envelope["analysis_error"] == "Decision model unavailable"
    assert envelope["failed_at"] == "2026-08-04T11:00:00"

    success_sql, success_params = db.fetch_query.call_args_list[1].args
    assert "decision_ok" in success_sql
    assert success_params == ("AAPL", "core")


@patch("services.report_service.get_db_client")
def test_latest_report_envelope_returns_failure_metadata_when_no_success_exists(mock_db):
    db = MagicMock()
    db.fetch_query.side_effect = [
        (
            [
                _row(
                    2,
                    "2026-08-04T11:00:00",
                    '{"decision_ok":false,"error":"Decision model unavailable"}',
                )
            ],
            REPORT_COLUMNS,
        ),
        ([], REPORT_COLUMNS),
    ]
    mock_db.return_value = db

    envelope = ReportService().get_latest_report_envelope("aapl", None)

    assert envelope == {
        "report": None,
        "analysis_failed": True,
        "analysis_error": "Decision model unavailable",
        "failed_at": "2026-08-04T11:00:00",
    }

    success_sql, success_params = db.fetch_query.call_args_list[1].args
    assert "report_type=%s" not in success_sql
    assert success_params == ("AAPL",)
