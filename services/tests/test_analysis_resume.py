from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from services.analysis_service import AnalysisService


def _service() -> AnalysisService:
    AnalysisService._instance = None
    return AnalysisService()


def test_core_reports_done_today_queries_hkt_utc_window():
    svc = _service()
    db = MagicMock()
    db.fetch_query.return_value = ([("aapl",), ("MSFT",)], ["ticker"])
    start = datetime(2026, 7, 21, 16, tzinfo=timezone.utc)
    end = datetime(2026, 7, 22, 16, tzinfo=timezone.utc)

    with (
        patch("services.analysis_service.get_db_client", return_value=db),
        patch(
            "services.analysis_service.rcs.day_bounds_utc",
            return_value=(start, end),
        ),
    ):
        result = svc._core_reports_done_today()

    assert result == {"AAPL", "MSFT"}
    sql, params = db.fetch_query.call_args.args
    assert "report_type = 'core'" in sql
    assert "created_at >= %s" in sql
    assert "created_at < %s" in sql
    assert params == (start, end)


def test_start_returns_already_completed_today_from_hybrid_done_set():
    svc = _service()
    universe = ["AAPL", "MSFT"]
    checkpoint = {
        "status": "partial",
        "completed": [{"ticker": "AAPL"}],
        "finished_at": "2026-07-22T01:00:00+00:00",
    }

    with (
        patch.object(svc.universe, "get_tickers", return_value=universe),
        patch("services.analysis_service.rcs.today_key", return_value="2026-07-22"),
        patch("services.analysis_service.rcs.load_analysis", return_value=checkpoint),
        patch.object(svc, "_core_reports_done_today", return_value={"MSFT"}),
    ):
        result = svc.start(force=False)

    assert result["started"] is False
    assert result["reason"] == "already_completed_today"
    assert result["date"] == "2026-07-22"


def test_start_resumes_only_todo_and_pins_day():
    svc = _service()
    universe = ["AAPL", "MSFT", "NVDA"]
    checkpoint = {
        "status": "partial",
        "tickers": universe,
        "completed": [{"ticker": "AAPL", "rating": "buy"}],
        "errors": [{"ticker": "OLD", "error": "old"}],
    }
    saved = []

    with (
        patch.object(svc.universe, "get_tickers", return_value=universe),
        patch("services.analysis_service.rcs.today_key", return_value="2026-07-22"),
        patch("services.analysis_service.rcs.load_analysis", return_value=checkpoint),
        patch("services.analysis_service.rcs.save_analysis",
              side_effect=lambda data, day=None: saved.append((dict(data), day))),
        patch.object(svc, "_core_reports_done_today", return_value={"MSFT"}),
        patch("services.analysis_service.threading.Thread") as thread_cls,
    ):
        result = svc.start()

    assert result["started"] is True
    assert result["resumed"] is True
    assert result["skipped"] == 2
    assert thread_cls.call_args.kwargs["args"][0] == ["NVDA"]
    assert thread_cls.call_args.kwargs["args"][2] == "2026-07-22"
    assert saved[-1][1] == "2026-07-22"
    assert {item["ticker"] for item in saved[-1][0]["completed"]} == {"AAPL", "MSFT"}
    assert saved[-1][0]["errors"] == []


def test_start_force_clears_checkpoint_and_regenerates_all():
    svc = _service()
    universe = ["AAPL", "MSFT"]
    checkpoint = {
        "status": "completed",
        "completed": [{"ticker": "AAPL"}, {"ticker": "MSFT"}],
        "errors": [{"ticker": "OLD", "error": "old"}],
    }
    saved = []

    with (
        patch.object(svc.universe, "get_tickers", return_value=universe),
        patch("services.analysis_service.rcs.today_key", return_value="2026-07-22"),
        patch("services.analysis_service.rcs.load_analysis", return_value=checkpoint),
        patch("services.analysis_service.rcs.save_analysis",
              side_effect=lambda data, day=None: saved.append((dict(data), day))),
        patch.object(svc, "_core_reports_done_today", return_value=set(universe)),
        patch("services.analysis_service.threading.Thread") as thread_cls,
    ):
        result = svc.start(force=True)

    assert result["started"] is True
    assert result["resumed"] is False
    assert result["skipped"] == 0
    assert thread_cls.call_args.kwargs["args"][0] == universe
    assert saved[-1][0]["completed"] == []
    assert saved[-1][0]["errors"] == []


def test_start_materializes_db_done_when_checkpoint_is_missing():
    svc = _service()
    universe = ["AAPL", "MSFT"]
    saved = []

    with (
        patch.object(svc.universe, "get_tickers", return_value=universe),
        patch("services.analysis_service.rcs.today_key", return_value="2026-07-22"),
        patch("services.analysis_service.rcs.load_analysis", return_value=None),
        patch("services.analysis_service.rcs.save_analysis",
              side_effect=lambda data, day=None: saved.append((dict(data), day))),
        patch.object(svc, "_core_reports_done_today", return_value={"AAPL"}),
        patch("services.analysis_service.threading.Thread") as thread_cls,
    ):
        result = svc.start()

    assert result["started"] is True
    assert thread_cls.call_args.kwargs["args"][0] == ["MSFT"]
    assert saved[-1][0]["completed"] == [{"ticker": "AAPL"}]


def test_get_status_embeds_daily_analysis_summary():
    svc = _service()
    svc._progress["tickers"] = ["AAPL"]
    checkpoint = {"status": "partial", "completed": [{"ticker": "AAPL"}]}
    daily = {"status": "partial", "can_resume": True}

    with (
        patch("services.analysis_service.rcs.load_analysis", return_value=checkpoint),
        patch(
            "services.analysis_service.rcs.daily_analysis_summary",
            return_value=daily,
        ) as summarize,
    ):
        result = svc.get_status()

    assert result["daily"] == daily
    summarize.assert_called_once_with(checkpoint, ["AAPL"])


def test_worker_checkpoints_each_success_and_completes():
    svc = _service()
    checkpoint = {
        "status": "running",
        "tickers": ["AAPL", "MSFT"],
        "completed": [{"ticker": "AAPL"}],
        "errors": [],
    }
    snapshots = []

    with (
        patch.object(
            svc,
            "_run_ticker_core_report",
            return_value={"rating": "buy", "score": 8, "report_id": 42},
        ),
        patch(
            "services.analysis_service.rcs.save_analysis",
            side_effect=lambda data, day=None: snapshots.append((dict(data), day)),
        ),
        patch("services.analysis_service.rcs.mark_last_analysis_date") as mark_last,
    ):
        svc._run_worker(
            ["MSFT"],
            {"per_ticker": 190, "total": 600, "mode": "core_report"},
            "2026-07-22",
            checkpoint,
        )

    assert any(
        {item["ticker"] for item in snap["completed"]} == {"AAPL", "MSFT"}
        for snap, _ in snapshots
    )
    assert snapshots[-1][0]["status"] == "completed"
    assert {day for _, day in snapshots} == {"2026-07-22"}
    mark_last.assert_called_once_with("2026-07-22")
    assert svc.get_status()["status"] == "done"


def test_worker_failure_persists_partial_checkpoint():
    svc = _service()
    checkpoint = {
        "status": "running",
        "tickers": ["AAPL"],
        "completed": [],
        "errors": [],
    }
    snapshots = []

    with (
        patch.object(
            svc,
            "_run_ticker_core_report",
            side_effect=RuntimeError("provider unavailable"),
        ),
        patch(
            "services.analysis_service.rcs.save_analysis",
            side_effect=lambda data, day=None: snapshots.append((dict(data), day)),
        ),
        patch("services.analysis_service.rcs.mark_last_analysis_date") as mark_last,
    ):
        svc._run_worker(
            ["AAPL"],
            {"per_ticker": 190, "total": 600, "mode": "core_report"},
            "2026-07-22",
            checkpoint,
        )

    assert snapshots[-1][0]["status"] == "failed"
    assert snapshots[-1][0]["errors"][0]["ticker"] == "AAPL"
    mark_last.assert_not_called()
