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
def test_find_last_good_fundamentals_skips_zero_defaults(mock_db):
    import json

    zeros = {
        "_inputs": {
            "forward_pe": None,
            "beta": None,
            "revenue_growth_pct": 0,
            "gross_margin_pct": 0,
            "fcf_margin_pct": 0,
            "cash_exceeds_debt": False,
        }
    }
    good = {
        "_inputs": {
            "forward_pe": 30.0,
            "beta": 1.2,
            "revenue_growth_pct": 40.0,
            "gross_margin_pct": 70.0,
            "fcf_margin_pct": 20.0,
            "cash_exceeds_debt": True,
        }
    }
    db = MagicMock()
    db.fetch_query.return_value = (
        [
            (json.dumps(zeros), "2026-10-06T00:00:00"),
            (json.dumps(good), "2026-09-29T00:00:00"),
        ],
        ["factor_scores", "created_at"],
    )
    mock_db.return_value = db

    found = ReportService().find_last_good_fundamentals("nvda", "core")

    assert found is not None
    assert found["inputs"]["forward_pe"] == 30.0
    assert found["as_of"] == "2026-09-29T00:00:00"
    sql, params = db.fetch_query.call_args.args
    assert "ORDER BY created_at DESC" in sql
    assert params == ("NVDA", "core", 12)


@patch("services.report_service.get_db_client")
def test_get_latest_report_typed_still_filters(mock_db):
    db = MagicMock()
    db.fetch_query.return_value = ([], ["id"])
    mock_db.return_value = db

    ReportService().get_latest_report("MSFT", "deep")

    sql, params = db.fetch_query.call_args.args
    assert "report_type=%s" in sql
    assert params == ("MSFT", "deep")


@patch("services.report_service.get_db_client")
def test_get_report_history_exposes_failed_decision_metadata(mock_db):
    db = MagicMock()
    db.fetch_query.return_value = (
        [
            (
                2,
                "AAPL",
                "core",
                "2026-08-04T11:00:00",
                None,
                None,
                "false",
                "Decision model unavailable",
            ),
            (
                1,
                "AAPL",
                "core",
                "2026-08-04T10:00:00",
                "BUY",
                "42",
                None,
                None,
            ),
        ],
        [
            "id",
            "ticker",
            "report_type",
            "created_at",
            "rating",
            "score",
            "decision_ok",
            "analysis_error",
        ],
    )
    mock_db.return_value = db

    history = ReportService().get_report_history("aapl")

    assert history[0]["decision_ok"] is False
    assert history[0]["analysis_failed"] is True
    assert history[0]["analysis_error"] == "Decision model unavailable"
    assert history[1]["decision_ok"] is True
    assert history[1]["analysis_failed"] is False
    sql, params = db.fetch_query.call_args.args
    assert "decision_ok" in sql
    assert "error_message" in sql
    assert params == ("AAPL",)
