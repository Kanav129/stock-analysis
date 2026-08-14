from unittest.mock import MagicMock, patch

from services.analysis_service import AnalysisService
from services.job_queue_service import JOB_CORE, JOB_DEEP, JobQueueService


def test_record_failed_analysis_saves_failed_rating_and_report():
    with (
        patch("services.analysis_failure_service.RatingsService") as ratings_cls,
        patch("services.analysis_failure_service.ReportService") as reports_cls,
    ):
        from services.analysis_failure_service import record_failed_analysis

        record_failed_analysis("aapl", "provider unavailable", report_type="deep")

    rating = ratings_cls.return_value.save_rating.call_args.args[0]
    assert rating["ticker"] == "AAPL"
    assert rating["report_type"] == "deep"
    assert rating["decision_ok"] is False
    assert rating["rating"] is None
    assert rating["score"] is None
    assert rating["error_message"] == "provider unavailable"

    report_call = reports_cls.return_value.save_report.call_args
    assert report_call.args[:2] == ("AAPL", "deep")
    assert report_call.kwargs["sections"] == {}
    assert report_call.kwargs["rating"]["decision_ok"] is False
    assert report_call.kwargs["rating"]["rating"] is None
    assert report_call.kwargs["rating"]["score"] is None
    assert report_call.kwargs["rating"]["error"] == "provider unavailable"


def test_execute_job_records_non_cancelled_deep_failure_before_finishing():
    JobQueueService._instance = None
    with patch("services.job_queue_service.UniverseService"):
        service = JobQueueService()
    service._run_deep = MagicMock(side_effect=RuntimeError("graph crashed"))
    service._should_stop = MagicMock(return_value=False)
    service._cancel_requested = MagicMock(return_value=False)
    events = []
    service._finish = MagicMock(side_effect=lambda *args, **kwargs: events.append("finish"))

    with patch(
        "services.job_queue_service.record_failed_analysis"
    ) as record_failure:
        record_failure.side_effect = lambda *args, **kwargs: events.append("record")
        service._execute_job({"id": "job-12345678", "ticker": "nvda", "job_type": JOB_DEEP})

    record_failure.assert_called_once_with("nvda", "graph crashed", report_type="deep")
    assert service._finish.call_args.args[:2] == ("job-12345678", "failed")
    assert events == ["record", "finish"]


def test_execute_job_does_not_record_cancelled_failure():
    JobQueueService._instance = None
    with patch("services.job_queue_service.UniverseService"):
        service = JobQueueService()
    service._run_core = MagicMock(side_effect=RuntimeError("Job cancelled"))
    service._should_stop = MagicMock(return_value=False)
    service._cancel_requested = MagicMock(return_value=True)
    service._finish = MagicMock()

    with patch(
        "services.job_queue_service.record_failed_analysis"
    ) as record_failure:
        service._execute_job({"id": "job-12345678", "ticker": "AAPL", "job_type": JOB_CORE})

    record_failure.assert_not_called()
    assert service._finish.call_args.args[:2] == ("job-12345678", "cancelled")


def test_analysis_worker_records_per_ticker_hard_failure():
    AnalysisService._instance = None
    service = AnalysisService()
    checkpoint = {
        "status": "running",
        "tickers": ["AAPL"],
        "completed": [],
        "errors": [],
    }

    with (
        patch.object(
            service,
            "_run_ticker_core_report",
            side_effect=RuntimeError("pipeline crashed"),
        ),
        patch("services.analysis_service.rcs.save_analysis"),
        patch(
            "services.analysis_service.record_failed_analysis"
        ) as record_failure,
    ):
        service._run_worker(
            ["AAPL"],
            {"per_ticker": 190, "total": 600, "mode": "core_report"},
            "2026-08-04",
            checkpoint,
        )

    record_failure.assert_called_once_with(
        "AAPL", "pipeline crashed", report_type="core"
    )


def test_rescore_worker_records_per_ticker_hard_failure_with_report_type():
    AnalysisService._instance = None
    service = AnalysisService()
    report = {"id": 7, "ticker": "NVDA", "report_type": "deep"}

    with (
        patch.object(
            service,
            "_rescore_ticker",
            side_effect=RuntimeError("rescore crashed"),
        ),
        patch(
            "services.analysis_service.record_failed_analysis"
        ) as record_failure,
    ):
        service._run_rescore_worker(["NVDA"], {"NVDA": report})

    record_failure.assert_called_once_with(
        "NVDA", "rescore crashed", report_type="deep"
    )
