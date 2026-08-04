"""Report history list + PDF export."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from services.report_pdf_service import build_report_pdf
from services.report_service import ReportService


@patch("services.report_service.get_db_client")
def test_get_report_history_includes_rating_and_score(mock_db):
    db = MagicMock()
    db.fetch_query.return_value = (
        [
            (
                10,
                "AAPL",
                "core",
                "2026-08-03T12:00:00",
                "BUY",
                "22",
            ),
            (
                9,
                "AAPL",
                "deep",
                "2026-07-20T09:00:00",
                "HOLD",
                "5",
            ),
        ],
        ["id", "ticker", "report_type", "created_at", "rating", "score"],
    )
    mock_db.return_value = db

    items = ReportService().get_report_history("aapl")

    assert len(items) == 2
    assert items[0]["id"] == 10
    assert items[0]["rating"] == "BUY"
    assert items[0]["score"] == 22
    assert items[0]["report_type"] == "core"
    assert items[1]["rating"] == "HOLD"
    assert items[1]["score"] == 5
    sql, params = db.fetch_query.call_args.args
    assert "ORDER BY created_at DESC" in sql
    assert "rating->>'rating'" in sql.replace(" ", "") or "rating ->>" in sql or "rating->>'rating'" in sql
    assert params == ("AAPL",)


@patch("services.report_service.get_db_client")
def test_get_report_by_id_scopes_to_ticker(mock_db):
    db = MagicMock()
    db.fetch_query.return_value = (
        [
            (
                10,
                "AAPL",
                "core",
                {"thesis": "ok"},
                {"rating": "BUY", "score": 22, "reasoning": "up"},
                None,
                None,
                190.0,
                "model-x",
                "2026-08-03T12:00:00",
            )
        ],
        [
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
        ],
    )
    mock_db.return_value = db

    report = ReportService().get_report_by_id("aapl", 10)

    assert report is not None
    assert report["id"] == 10
    sql, params = db.fetch_query.call_args.args
    assert "id=%s" in sql
    assert "ticker=%s" in sql
    assert params == (10, "AAPL")


@patch("services.report_service.get_db_client")
def test_get_report_by_id_returns_none_when_missing(mock_db):
    db = MagicMock()
    db.fetch_query.return_value = ([], ["id"])
    mock_db.return_value = db

    assert ReportService().get_report_by_id("AAPL", 999) is None


def test_build_report_pdf_returns_pdf_bytes():
    report = {
        "id": 10,
        "ticker": "AAPL",
        "report_type": "core",
        "created_at": "2026-08-03T12:00:00",
        "model": "test-model",
        "live_price": 190.5,
        "rating": {
            "rating": "BUY",
            "score": 22,
            "reasoning": "Momentum and earnings look strong.",
            "key_drivers": ["EPS beat", "Guidance raise"],
        },
        "entry_levels": {"entry": 185, "stop": 170, "target": 210, "position_note": "starter"},
        "factor_scores": {"market": 15, "fundamentals": 20},
        "sections": {
            "market": "## Market\nPrice above SMA50.",
            "fundamentals": "Margins expanding.",
            "_kronos_data": {"ignore": True},
        },
    }

    pdf = build_report_pdf(report)

    assert isinstance(pdf, (bytes, bytearray))
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 200
