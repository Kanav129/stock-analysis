from unittest.mock import MagicMock, patch

from services.ratings_service import RatingsService


@patch("services.ratings_service.get_db_client")
def test_get_recent_ratings_orders_newest_first(mock_db):
    db = MagicMock()
    db.fetch_query.return_value = (
        [
            (2, "MSFT", "BUY", 40, "r", "[]", "[]", "{}", "m", "deep", MagicMock(isoformat=lambda: "2026-08-01T12:00:00")),
            (1, "AAPL", "HOLD", 5, "r", "[]", "[]", "{}", "m", "core", MagicMock(isoformat=lambda: "2026-08-01T11:00:00")),
        ],
        [
            "id", "ticker", "rating", "score", "reasoning",
            "key_drivers", "supporting_headlines", "price_summary", "model", "report_type", "created_at",
        ],
    )
    mock_db.return_value = db

    out = RatingsService().get_recent_ratings(8)

    assert [r["ticker"] for r in out] == ["MSFT", "AAPL"]
    sql, params = db.fetch_query.call_args.args
    assert "DISTINCT ON (ticker)" in sql
    assert "ORDER BY ticker, created_at DESC" in sql
    assert "created_at >=" in sql
    assert "INTERVAL '1 day'" in sql
    assert "LIMIT %s" in sql
    assert params == (5, 8)


@patch("services.ratings_service.get_db_client")
def test_get_recent_ratings_clamps_limit(mock_db):
    db = MagicMock()
    db.fetch_query.return_value = ([], ["id"])
    mock_db.return_value = db

    RatingsService().get_recent_ratings(999)
    assert db.fetch_query.call_args.args[1] == (5, 50)

    RatingsService().get_recent_ratings(0)
    assert db.fetch_query.call_args.args[1] == (5, 1)


def test_failed_rating_row_preserves_null_decision():
    out = RatingsService._row_to_dict(
        ["rating", "score", "decision_ok", "error_message"],
        (None, None, False, "decision providers unavailable"),
    )

    assert out["decision_ok"] is False
    assert out["rating"] is None
    assert out["score"] is None
    assert out["error_message"] == "decision providers unavailable"
