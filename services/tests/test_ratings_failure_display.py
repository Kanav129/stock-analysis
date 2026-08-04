from datetime import datetime
from unittest.mock import MagicMock, patch

from services import ratings_service


def _rating(
    *,
    created_at: str,
    decision_ok: bool,
    rating: str | None = None,
    score: int | None = None,
    error_message: str | None = None,
) -> dict:
    return {
        "ticker": "AAPL",
        "rating": rating,
        "score": score,
        "decision_ok": decision_ok,
        "error_message": error_message,
        "created_at": created_at,
    }


def test_merge_success_only_has_no_analysis_failure():
    success = _rating(
        created_at="2026-08-04T10:00:00",
        decision_ok=True,
        rating="BUY",
        score=42,
    )

    assert ratings_service.merge_success_and_failure(success, None) == success


def test_merge_newer_failure_keeps_last_successful_decision():
    success = _rating(
        created_at="2026-08-04T10:00:00",
        decision_ok=True,
        rating="BUY",
        score=42,
    )
    failure = _rating(
        created_at="2026-08-04T11:00:00",
        decision_ok=False,
        error_message="decision providers unavailable",
    )

    merged = ratings_service.merge_success_and_failure(success, failure)

    assert merged is not None
    assert merged["rating"] == "BUY"
    assert merged["score"] == 42
    assert merged["analysis_failed"] is True
    assert merged["analysis_error"] == "decision providers unavailable"
    assert merged["failed_at"] == "2026-08-04T11:00:00"


def test_merge_failure_only_never_synthesizes_hold_or_zero():
    failure = _rating(
        created_at="2026-08-04T11:00:00",
        decision_ok=False,
        error_message="decision providers unavailable",
    )

    merged = ratings_service.merge_success_and_failure(None, failure)

    assert merged is not None
    assert merged["rating"] is None
    assert merged["score"] is None
    assert merged["analysis_failed"] is True
    assert merged["analysis_error"] == "decision providers unavailable"
    assert merged["failed_at"] == "2026-08-04T11:00:00"


def test_legacy_null_decision_flag_is_treated_as_success():
    result = ratings_service.RatingsService._row_to_dict(
        ["rating", "score", "decision_ok", "error_message"],
        ("BUY", 42, None, None),
    )

    assert result["decision_ok"] is True
    assert result["analysis_failed"] is False
    assert result["rating"] == "BUY"
    assert result["score"] == 42


def test_failed_rating_row_exposes_history_failure_fields():
    result = ratings_service.RatingsService._row_to_dict(
        ["rating", "score", "decision_ok", "error_message"],
        (None, None, False, "Decision model unavailable"),
    )

    assert result["decision_ok"] is False
    assert result["error_message"] == "Decision model unavailable"
    assert result["analysis_failed"] is True


@patch("services.ratings_service.get_db_client")
def test_latest_analysis_merges_newer_failed_row(mock_db):
    cols = [
        "id", "ticker", "rating", "score", "reasoning",
        "key_drivers", "supporting_headlines", "price_summary", "model",
        "report_type", "decision_ok", "error_message", "created_at",
    ]
    mock_db.return_value.fetch_query.return_value = (
        [
            (2, "AAPL", None, None, "failed", [], [], {}, "m", "core", False,
             "provider unavailable", datetime(2026, 8, 4, 11)),
            (1, "AAPL", "BUY", 42, "good", [], [], {}, "m", "core", True,
             None, datetime(2026, 8, 4, 10)),
        ],
        cols,
    )

    result = ratings_service.RatingsService()._latest_analysis_ratings(["AAPL"])

    assert result[0]["rating"] == "BUY"
    assert result[0]["score"] == 42
    assert result[0]["analysis_failed"] is True
    assert result[0]["analysis_error"] == "provider unavailable"


@patch("services.ratings_service.get_db_client")
def test_latest_report_merges_newer_failed_json_rating(mock_db):
    mock_db.return_value.fetch_query.return_value = (
        [
            (
                2, "AAPL", "core", None, None, None, "failed", [], "m",
                False, "provider unavailable", datetime(2026, 8, 4, 11),
            ),
            (
                1, "AAPL", "core", "BUY", "42", None, "good", [], "m",
                True, None, datetime(2026, 8, 4, 10),
            ),
        ],
        [],
    )

    result = ratings_service.RatingsService()._latest_report_ratings(["AAPL"])

    assert result[0]["rating"] == "BUY"
    assert result[0]["score"] == 42
    assert result[0]["analysis_failed"] is True
    assert result[0]["failed_at"] == "2026-08-04T11:00:00"


@patch("services.ratings_service.get_db_client")
def test_recent_ratings_merges_failure_and_orders_by_latest_attempt(mock_db):
    cols = [
        "id", "ticker", "rating", "score", "reasoning",
        "key_drivers", "supporting_headlines", "price_summary", "model",
        "report_type", "decision_ok", "error_message", "created_at",
    ]
    mock_db.return_value.fetch_query.return_value = (
        [
            (2, "AAPL", None, None, "failed", [], [], {}, "m", "core", False,
             "provider unavailable", datetime(2026, 8, 4, 12)),
            (3, "MSFT", "SELL", -30, "new", [], [], {}, "m", "deep", True,
             None, datetime(2026, 8, 4, 11)),
            (1, "AAPL", "BUY", 42, "old", [], [], {}, "m", "core", True,
             None, datetime(2026, 8, 4, 10)),
        ],
        cols,
    )

    result = ratings_service.RatingsService().get_recent_ratings(8)

    assert [item["ticker"] for item in result] == ["AAPL", "MSFT"]
    assert result[0]["rating"] == "BUY"
    assert result[0]["analysis_failed"] is True


def test_get_latest_keeps_report_success_and_cross_source_failure_metadata():
    service = ratings_service.RatingsService()
    service._latest_report_ratings = MagicMock(return_value=[
        _rating(
            created_at="2026-08-04T10:00:00",
            decision_ok=True,
            rating="BUY",
            score=42,
        )
    ])
    service._latest_analysis_ratings = MagicMock(return_value=[
        {
            **_rating(
                created_at="2026-08-04T11:00:00",
                decision_ok=False,
                error_message="provider unavailable",
            ),
            "analysis_failed": True,
            "analysis_error": "provider unavailable",
            "failed_at": "2026-08-04T11:00:00",
        }
    ])

    result = service.get_latest_ratings(["AAPL"])

    assert result[0]["rating"] == "BUY"
    assert result[0]["score"] == 42
    assert result[0]["analysis_failed"] is True
    assert result[0]["analysis_error"] == "provider unavailable"


@patch("services.ratings_service.get_db_client")
def test_list_tickers_with_latest_failure_uses_latest_attempt_across_sources(mock_db):
    mock_db.return_value.fetch_query.return_value = (
        [("AAPL", "core"), ("MSFT", "deep")],
        ["ticker", "report_type"],
    )

    result = ratings_service.RatingsService().list_tickers_with_latest_failure()

    assert result == ["AAPL", "MSFT"]
    query = mock_db.return_value.fetch_query.call_args.args[0]
    assert "stock_ratings" in query
    assert "stock_reports" in query
    assert "DISTINCT ON (ticker)" in query
    assert "report_type" in query


@patch("services.ratings_service.get_db_client")
def test_list_latest_failures_preserves_report_type(mock_db):
    mock_db.return_value.fetch_query.return_value = (
        [("AAPL", "core"), ("NVDA", "deep")],
        ["ticker", "report_type"],
    )

    result = ratings_service.RatingsService().list_latest_failures()

    assert result == [
        {"ticker": "AAPL", "report_type": "core"},
        {"ticker": "NVDA", "report_type": "deep"},
    ]
