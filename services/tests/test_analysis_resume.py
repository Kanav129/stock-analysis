from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from services.analysis_service import AnalysisService


def _service() -> AnalysisService:
    AnalysisService._instance = None
    return AnalysisService()


def test_core_reports_done_today_queries_pinned_hkt_utc_window():
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
        ) as bounds,
    ):
        result = svc._core_reports_done_today("2026-07-22")

    assert result == {"AAPL", "MSFT"}
    bounds.assert_called_once_with("2026-07-22")
    sql, params = db.fetch_query.call_args.args
    assert "report_type = 'core'" in sql
    assert "created_at >= %s" in sql
    assert "created_at < %s" in sql
    assert params == (start, end)


def test_start_returns_already_completed_today_from_hybrid_done_set():
    svc = _service()
    universe = ["AAPL", "MSFT"]

    with (
        patch.object(svc.universe, "get_tickers", return_value=universe),
        patch("services.analysis_service.rcs.today_key", return_value="2026-07-22"),
        patch(
            "services.job_queue_service.job_queue_service.enqueue",
            return_value={
                "started": False,
                "reason": "already_completed_today",
                "date": "2026-07-22",
                "enqueued": [],
                "reused": [],
                "skipped_completed": ["AAPL", "MSFT"],
                "message": "Core analysis already completed today.",
                "jobs": [],
            },
        ),
        patch("services.job_queue_service.job_queue_service.ensure_started"),
        patch(
            "services.job_queue_service.job_queue_service.list_jobs",
            return_value=[],
        ),
        patch("services.analysis_service.rcs.load_analysis", return_value=None),
        patch.object(svc, "_core_reports_done_today", return_value=set()),
        patch(
            "services.analysis_service.rcs.daily_analysis_summary",
            return_value={"already_completed_today": True},
        ),
    ):
        result = svc.start(force=False)

    assert result["started"] is False
    assert result["reason"] == "already_completed_today"
    assert result["date"] == "2026-07-22"


def test_start_resumes_only_todo_and_pins_day():
    svc = _service()
    universe = ["AAPL", "MSFT", "NVDA"]

    with (
        patch.object(svc.universe, "get_tickers", return_value=universe),
        patch("services.analysis_service.rcs.today_key", return_value="2026-07-22"),
        patch("services.analysis_service.rcs.load_analysis", return_value=None),
        patch.object(svc, "_core_reports_done_today", return_value={"MSFT"}),
        patch(
            "services.job_queue_service.job_queue_service.enqueue",
            return_value={
                "started": True,
                "enqueued": [{"id": "1", "ticker": "NVDA"}],
                "reused": [],
                "skipped_completed": ["AAPL", "MSFT"],
                "message": "Queued 1",
                "jobs": [{"id": "1", "ticker": "NVDA"}],
            },
        ) as enq,
        patch("services.job_queue_service.job_queue_service.ensure_started"),
        patch(
            "services.job_queue_service.job_queue_service.list_jobs",
            return_value=[],
        ),
        patch(
            "services.analysis_service.rcs.daily_analysis_summary",
            return_value={},
        ),
    ):
        result = svc.start()

    assert result["started"] is True
    assert result["resumed"] is True
    assert result["skipped"] == 2
    enq.assert_called_once()
    assert enq.call_args.args[1] == universe


def test_start_force_clears_checkpoint_and_regenerates_all():
    svc = _service()
    universe = ["AAPL", "MSFT"]

    with (
        patch.object(svc.universe, "get_tickers", return_value=universe),
        patch("services.analysis_service.rcs.today_key", return_value="2026-07-22"),
        patch("services.analysis_service.rcs.load_analysis", return_value=None),
        patch.object(svc, "_core_reports_done_today", return_value=set(universe)),
        patch(
            "services.job_queue_service.job_queue_service.enqueue",
            return_value={
                "started": True,
                "enqueued": [{"id": "1", "ticker": "AAPL"}, {"id": "2", "ticker": "MSFT"}],
                "reused": [],
                "skipped_completed": [],
                "message": "Queued 2",
                "jobs": [{"id": "1", "ticker": "AAPL"}, {"id": "2", "ticker": "MSFT"}],
            },
        ) as enq,
        patch("services.job_queue_service.job_queue_service.ensure_started"),
        patch(
            "services.job_queue_service.job_queue_service.list_jobs",
            return_value=[],
        ),
        patch(
            "services.analysis_service.rcs.daily_analysis_summary",
            return_value={},
        ),
    ):
        result = svc.start(force=True)

    assert result["started"] is True
    assert result["resumed"] is False
    assert result["skipped"] == 0
    enq.assert_called_once()
    assert enq.call_args.kwargs.get("force") is True or (
        len(enq.call_args.args) >= 3 and enq.call_args.args[2] is True
    ) or enq.call_args.kwargs.get("force") is True
    # force passed as keyword
    assert enq.call_args.kwargs["force"] is True
    assert enq.call_args.args[1] == universe


def test_start_materializes_db_done_when_checkpoint_is_missing():
    svc = _service()
    universe = ["AAPL", "MSFT"]

    with (
        patch.object(svc.universe, "get_tickers", return_value=universe),
        patch("services.analysis_service.rcs.today_key", return_value="2026-07-22"),
        patch("services.analysis_service.rcs.load_analysis", return_value=None),
        patch.object(svc, "_core_reports_done_today", return_value={"AAPL"}),
        patch(
            "services.job_queue_service.job_queue_service.enqueue",
            return_value={
                "started": True,
                "enqueued": [{"id": "1", "ticker": "MSFT"}],
                "reused": [],
                "skipped_completed": ["AAPL"],
                "message": "Queued 1",
                "jobs": [{"id": "1", "ticker": "MSFT"}],
            },
        ) as enq,
        patch("services.job_queue_service.job_queue_service.ensure_started"),
        patch(
            "services.job_queue_service.job_queue_service.list_jobs",
            return_value=[],
        ),
        patch(
            "services.analysis_service.rcs.daily_analysis_summary",
            return_value={},
        ),
    ):
        result = svc.start()

    assert result["started"] is True
    enq.assert_called_once()
    assert enq.call_args.args[1] == universe


def test_get_status_embeds_daily_analysis_summary():
    svc = _service()
    svc._progress["tickers"] = ["AAPL"]
    universe = ["AAPL", "MSFT"]
    checkpoint = {"status": "partial", "completed": [{"ticker": "AAPL"}]}
    daily = {"status": "partial", "can_resume": True}

    with (
        patch.object(svc.universe, "get_tickers", return_value=universe),
        patch("services.analysis_service.rcs.today_key", return_value="2026-07-22"),
        patch("services.analysis_service.rcs.load_analysis", return_value=checkpoint),
        patch.object(svc, "_core_reports_done_today", return_value=set()),
        patch(
            "services.analysis_service.rcs.daily_analysis_summary",
            return_value=daily,
        ) as summarize,
        patch("services.job_queue_service.job_queue_service.ensure_started"),
        patch(
            "services.job_queue_service.job_queue_service.count_active",
            return_value=0,
        ),
        patch(
            "services.job_queue_service.job_queue_service.list_jobs",
            return_value=[],
        ) as list_jobs,
    ):
        result = svc.get_status()

    assert result["daily"] == daily
    list_jobs.assert_not_called()
    summary_checkpoint, summary_universe = summarize.call_args.args
    assert summary_checkpoint == checkpoint
    assert summary_universe == universe


def test_get_status_daily_summary_includes_core_reports_done_today():
    svc = _service()
    universe = ["AAPL", "MSFT"]
    checkpoint = {"status": "partial", "completed": []}

    with (
        patch.object(svc.universe, "get_tickers", return_value=universe),
        patch("services.analysis_service.rcs.today_key", return_value="2026-07-22"),
        patch("services.analysis_service.rcs.load_analysis", return_value=checkpoint),
        patch.object(
            svc,
            "_core_reports_done_today",
            return_value={"AAPL", "MSFT"},
        ) as done_today,
        patch("services.job_queue_service.job_queue_service.ensure_started"),
        patch(
            "services.job_queue_service.job_queue_service.count_active",
            return_value=0,
        ),
        patch(
            "services.job_queue_service.job_queue_service.list_jobs",
            return_value=[],
        ),
    ):
        result = svc.get_status()

    assert result["daily"]["already_completed_today"] is True
    done_today.assert_called()
    assert result["daily"]["completed_count"] == 2
    done_today.assert_called_once_with("2026-07-22")


def test_get_status_idle_reuses_daily_cache():
    svc = _service()
    universe = ["AAPL"]
    daily = {"status": "partial", "can_resume": True, "already_completed_today": False}

    with (
        patch.object(svc.universe, "get_tickers", return_value=universe),
        patch("services.analysis_service.rcs.today_key", return_value="2026-07-22"),
        patch("services.analysis_service.rcs.load_analysis", return_value=None),
        patch.object(svc, "_core_reports_done_today", return_value=set()) as done_today,
        patch(
            "services.analysis_service.rcs.daily_analysis_summary",
            return_value=daily,
        ) as summarize,
        patch("services.job_queue_service.job_queue_service.ensure_started"),
        patch(
            "services.job_queue_service.job_queue_service.count_active",
            return_value=0,
        ),
    ):
        first = svc.get_status()
        second = svc.get_status()

    assert first["daily"] == daily
    assert second["daily"] == daily
    assert summarize.call_count == 1
    assert done_today.call_count == 1


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
    assert svc._progress["status"] == "done"


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
