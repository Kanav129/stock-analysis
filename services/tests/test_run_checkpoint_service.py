from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from services import run_checkpoint_service as rcs


def test_today_key_uses_hkt_not_utc():
    # 2026-07-21 20:30 UTC == 2026-07-22 04:30 HKT
    fixed = datetime(2026, 7, 21, 20, 30, tzinfo=timezone.utc)
    with patch.object(rcs, "_now_utc", return_value=fixed):
        with patch.dict("os.environ", {"APP_TIMEZONE": "Asia/Hong_Kong"}, clear=False):
            assert rcs.today_key() == "2026-07-22"


def test_day_bounds_utc_hkt():
    start, end = rcs.day_bounds_utc("2026-07-22")
    assert start == datetime(2026, 7, 21, 16, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 7, 22, 16, 0, tzinfo=timezone.utc)


def test_is_sync_complete_requires_vectors_and_all_tickers():
    universe = ["AAPL", "MSFT"]
    cp = {
        "status": "completed",
        "news_done": ["AAPL", "MSFT"],
        "prices_done": ["AAPL", "MSFT"],
        "vectors_done": False,
    }
    assert rcs.is_sync_complete_for_universe(cp, universe) is False
    cp["vectors_done"] = True
    assert rcs.is_sync_complete_for_universe(cp, universe) is True
    # Universe grew
    assert rcs.is_sync_complete_for_universe(cp, ["AAPL", "MSFT", "NVDA"]) is False


def test_sync_todos_resume_and_force():
    universe = ["AAPL", "MSFT", "NVDA"]
    cp = {
        "status": "partial",
        "news_done": ["AAPL", "MSFT"],
        "prices_done": ["AAPL"],
        "vectors_done": False,
    }
    todos = rcs.sync_todos(cp, universe, force=False)
    assert todos["news_todo"] == ["NVDA"]
    assert todos["prices_todo"] == ["MSFT", "NVDA"]
    assert todos["need_vectors"] is True
    assert todos["resumed"] is True

    forced = rcs.sync_todos(cp, universe, force=True)
    assert forced["news_todo"] == universe
    assert forced["prices_todo"] == universe
    assert forced["cleared"] is True


def test_daily_analysis_summary_does_not_complete_failed_decisions():
    """Failure rows and ticker-only stubs are not a finished analysis day."""
    cp = {
        "status": "completed",
        "tickers": ["AAPL", "MSFT"],
        "completed": [
            {"ticker": "AAPL", "rating": None, "score": None, "decision_ok": False},
            {"ticker": "MSFT"},
        ],
        "finished_at": "2026-10-26T04:00:00",
    }
    summary = rcs.daily_analysis_summary(cp, ["AAPL", "MSFT"])
    assert summary["already_completed_today"] is False
    assert summary["ratings_ok"] is False
    assert summary["good_count"] == 0
    assert summary["completed_count"] == 0
    assert summary["status"] == "partial"
    assert summary["can_resume"] is True


def test_daily_analysis_summary_accepts_legacy_and_verified_reports():
    legacy = {
        "status": "completed",
        "completed": [
            {"ticker": "AAPL", "rating": "BUY", "score": 10},
            {"ticker": "MSFT", "rating": "HOLD", "score": 0, "decision_ok": True},
        ],
    }
    summary = rcs.daily_analysis_summary(legacy, ["AAPL", "MSFT"])
    assert summary["already_completed_today"] is True
    assert summary["ratings_ok"] is True
    assert summary["good_count"] == 2
    assert summary["can_resume"] is False

    verified = {
        "status": "completed",
        "completed": [
            {"ticker": "AAPL", "verified_report": True},
            {"ticker": "MSFT", "verified_report": True},
        ],
    }
    verified_summary = rcs.daily_analysis_summary(verified, ["AAPL", "MSFT"])
    assert verified_summary["ratings_ok"] is True
    assert verified_summary["good_count"] == 2


def test_daily_analysis_summary_partial_when_only_some_decisions_ok():
    cp = {
        "status": "completed",
        "completed": [
            {"ticker": "AAPL", "rating": "BUY", "score": 8, "decision_ok": True},
            {"ticker": "MSFT", "rating": None, "score": None, "decision_ok": False},
        ],
    }
    summary = rcs.daily_analysis_summary(cp, ["AAPL", "MSFT"])
    assert summary["already_completed_today"] is False
    assert summary["ratings_ok"] is False
    assert summary["good_count"] == 1
    assert summary["can_resume"] is True
    assert summary["status"] == "partial"


def test_save_json_upserts_app_settings():
    db = MagicMock()
    with patch("services.run_checkpoint_service.get_db_client", return_value=db):
        rcs.save_json("daily_sync:2026-07-22", {"status": "running", "news_done": []})
    db.execute_query.assert_called_once()
    sql, params = db.execute_query.call_args[0]
    assert "INSERT INTO app_settings" in sql
    assert params[0] == "daily_sync:2026-07-22"
    assert '"status": "running"' in params[1] or '"status":"running"' in params[1].replace(" ", "")
