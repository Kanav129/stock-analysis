"""ReportService: latest report must be chronological, not deep-over-core."""
from unittest.mock import MagicMock, patch

from services.report_service import ReportService, resolve_report_type_filter


def test_resolve_report_type_filter_latest_means_any_type():
    assert resolve_report_type_filter("latest") is None
    assert resolve_report_type_filter("any") is None
    assert resolve_report_type_filter("") is None
    assert resolve_report_type_filter(None) is None
    assert resolve_report_type_filter("core") == "core"
    assert resolve_report_type_filter("deep") == "deep"
    assert resolve_report_type_filter("DEEP") == "deep"


def test_resolve_report_type_filter_rejects_unknown():
    try:
        resolve_report_type_filter("weekly")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "core" in str(exc).lower() or "latest" in str(exc).lower()


@patch("services.report_service.get_db_client")
def test_get_latest_report_any_type_orders_by_created_at(mock_db):
    db = MagicMock()
    db.fetch_query.return_value = (
        [
            (
                99,
                "AAPL",
                "core",
                "{}",
                '{"rating":"BUY","score":20}',
                None,
                None,
                190.0,
                "model-new",
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

    out = ReportService().get_latest_report("aapl", None)

    assert out is not None
    assert out["id"] == 99
    assert out["report_type"] == "core"
    sql, params = db.fetch_query.call_args.args
    assert "WHERE ticker=%s" in sql
    assert "report_type=%s" not in sql
    assert "ORDER BY created_at DESC LIMIT 1" in sql
    assert params == ("AAPL",)


@patch("services.report_service.get_db_client")
def test_get_latest_report_typed_still_filters(mock_db):
    db = MagicMock()
    db.fetch_query.return_value = ([], ["id"])
    mock_db.return_value = db

    ReportService().get_latest_report("MSFT", "deep")

    sql, params = db.fetch_query.call_args.args
    assert "report_type=%s" in sql
    assert params == ("MSFT", "deep")
