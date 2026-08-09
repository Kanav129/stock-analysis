"""Same-day core → deep continue, and auto-enqueue deep after strong core scores."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from services.report_service import ReportService, core_sections_for_continue


def test_core_sections_for_continue_strips_deep_only_keys():
    sections = {
        "fundamentals": "f",
        "news": "n",
        "sentiment": "s",
        "flows": "drop",
        "policy": "drop",
        "lockup": "drop",
        "kronos": "drop",
        "_kronos_data": {"forecast": []},
        "research_plan": "drop",
    }
    out = core_sections_for_continue(sections)
    assert out == {"fundamentals": "f", "news": "n", "sentiment": "s"}


def test_core_sections_for_continue_handles_empty():
    assert core_sections_for_continue(None) == {}
    assert core_sections_for_continue({}) == {}


@patch("services.report_service.get_db_client")
@patch("services.report_service.rcs.day_bounds_utc")
def test_get_same_day_core_report_queries_hkt_window(mock_bounds, mock_db):
    start = datetime(2026, 8, 8, 16, tzinfo=timezone.utc)
    end = datetime(2026, 8, 9, 16, tzinfo=timezone.utc)
    mock_bounds.return_value = (start, end)
    db = MagicMock()
    db.fetch_query.return_value = (
        [
            (
                11,
                "AAPL",
                "core",
                '{"fundamentals":"ok"}',
                '{"rating":"BUY","score":42}',
                '{"value":50}',
                None,
                190.0,
                "model",
                "2026-08-09T02:00:00",
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

    out = ReportService().get_same_day_core_report("aapl", day="2026-08-09")

    assert out is not None
    assert out["id"] == 11
    assert out["sections"]["fundamentals"] == "ok"
    mock_bounds.assert_called_once_with("2026-08-09")
    sql, params = db.fetch_query.call_args.args
    assert "report_type=%s" in sql
    assert "created_at >= %s" in sql
    assert "created_at < %s" in sql
    assert params == ("AAPL", "core", start, end)


@patch("services.report_service.get_db_client")
@patch("services.report_service.rcs.day_bounds_utc")
def test_get_same_day_report_returns_none_outside_window(mock_bounds, mock_db):
    mock_bounds.return_value = (
        datetime(2026, 8, 8, 16, tzinfo=timezone.utc),
        datetime(2026, 8, 9, 16, tzinfo=timezone.utc),
    )
    db = MagicMock()
    db.fetch_query.return_value = ([], ["id"])
    mock_db.return_value = db

    assert ReportService().get_same_day_deep_report("MSFT") is None


def test_continue_deep_from_core_skips_core_llm_gathers_and_omits_report_id():
    from services.analysis_service import AnalysisService

    AnalysisService._instance = None
    svc = AnalysisService()
    core = {
        "id": 55,
        "ticker": "NVDA",
        "sections": {
            "fundamentals": "fund",
            "news": "news",
            "sentiment": "sent",
            "flows": "stale",
        },
        "factor_scores": {"value": 60},
        "live_price": 120.0,
    }
    stages_seen: list[str] = []

    def _prices(state):
        stages_seen.append("gather_prices")
        return {"market_data": {"volume_latest": 1}, "live_price": 121.0}

    def _flows(state):
        stages_seen.append("gather_flows")
        assert "report_id" not in state
        assert state["report_type"] == "deep"
        assert state["sections_markdown"]["fundamentals"] == "fund"
        assert "flows" not in state["sections_markdown"]
        assert state["factor_scores"]["value"] == 60
        return {"sections_markdown": {**state["sections_markdown"], "flows": "new"}}

    def _policy(state):
        stages_seen.append("gather_policy")
        return {}

    def _lockup(state):
        stages_seen.append("gather_lockup")
        return {}

    def _kronos(state):
        stages_seen.append("run_kronos")
        return {}

    def _debate(state):
        stages_seen.append("debate")
        return {}

    def _decision(state):
        stages_seen.append("synthesize_decision")
        return {"rating": "BUY", "score": 45, "decision_ok": True}

    def _persist(state):
        stages_seen.append("persist")
        assert "report_id" not in state
        return {"report_id": 99}

    with (
        patch("services.analysis_service.gather_prices", side_effect=_prices),
        patch("services.analysis_service.gather_flows", side_effect=_flows),
        patch("services.analysis_service.gather_policy", side_effect=_policy),
        patch("services.analysis_service.gather_lockup", side_effect=_lockup),
        patch("services.analysis_service.run_kronos", side_effect=_kronos),
        patch("services.analysis_service.debate", side_effect=_debate),
        patch("services.analysis_service.synthesize_decision", side_effect=_decision),
        patch("services.analysis_service.persist_report", side_effect=_persist),
        patch("services.analysis_service.gather_fundamentals", create=True) as fund,
        patch("services.analysis_service.gather_news", create=True) as news,
        patch("services.analysis_service.gather_sentiment", create=True) as sent,
    ):
        out = svc._continue_deep_from_core(core, should_cancel=lambda: False)

    assert out["report_id"] == 99
    assert out["score"] == 45
    assert stages_seen == [
        "gather_prices",
        "gather_flows",
        "gather_policy",
        "gather_lockup",
        "run_kronos",
        "debate",
        "synthesize_decision",
        "persist",
    ]
    fund.assert_not_called()
    news.assert_not_called()
    sent.assert_not_called()


def test_maybe_auto_enqueue_deep_when_abs_score_ge_20():
    from services.job_queue_service import JobQueueService

    svc = JobQueueService()
    with (
        patch.object(svc, "find_active", return_value=None),
        patch(
            "services.report_service.ReportService.get_same_day_deep_report",
            return_value=None,
        ),
        patch.object(svc, "enqueue", return_value={"started": True}) as enq,
    ):
        svc._maybe_auto_enqueue_deep("aapl", {"score": 20, "decision_ok": True})

    enq.assert_called_once_with("deep_dive", ["AAPL"])


def test_maybe_auto_enqueue_deep_negative_score_threshold():
    from services.job_queue_service import JobQueueService

    svc = JobQueueService()
    with (
        patch.object(svc, "find_active", return_value=None),
        patch(
            "services.report_service.ReportService.get_same_day_deep_report",
            return_value=None,
        ),
        patch.object(svc, "enqueue", return_value={"started": True}) as enq,
    ):
        svc._maybe_auto_enqueue_deep("MSFT", {"score": -25})

    enq.assert_called_once_with("deep_dive", ["MSFT"])


def test_maybe_auto_enqueue_deep_skips_below_threshold():
    from services.job_queue_service import JobQueueService

    svc = JobQueueService()
    with patch.object(svc, "enqueue") as enq:
        svc._maybe_auto_enqueue_deep("AAPL", {"score": 19})
        svc._maybe_auto_enqueue_deep("AAPL", {"score": -19})
        svc._maybe_auto_enqueue_deep("AAPL", {})
        svc._maybe_auto_enqueue_deep("AAPL", {"score": 40, "decision_ok": False})

    enq.assert_not_called()


def test_maybe_auto_enqueue_deep_skips_when_same_day_deep_exists():
    from services.job_queue_service import JobQueueService

    svc = JobQueueService()
    with (
        patch.object(svc, "find_active", return_value=None),
        patch(
            "services.report_service.ReportService.get_same_day_deep_report",
            return_value={"id": 1},
        ),
        patch.object(svc, "enqueue") as enq,
    ):
        svc._maybe_auto_enqueue_deep("AAPL", {"score": 50})

    enq.assert_not_called()


def test_maybe_auto_enqueue_deep_skips_when_deep_active():
    from services.job_queue_service import JobQueueService

    svc = JobQueueService()
    with (
        patch.object(svc, "find_active", return_value={"id": "job-1"}),
        patch.object(svc, "enqueue") as enq,
    ):
        svc._maybe_auto_enqueue_deep("AAPL", {"score": 50})

    enq.assert_not_called()


def test_run_deep_uses_continue_path_when_same_day_core_exists():
    from services.job_queue_service import JobQueueService

    JobQueueService._instance = None
    svc = JobQueueService()
    core = {"id": 7, "ticker": "AAPL", "sections": {}, "factor_scores": {}}
    analysis = MagicMock()
    analysis._continue_deep_from_core.return_value = {
        "report_id": 88,
        "rating": "BUY",
        "score": 33,
    }
    graph_app = MagicMock()

    with (
        patch(
            "services.report_service.ReportService.get_same_day_core_report",
            return_value=core,
        ),
        patch(
            "services.analysis_service.analysis_service",
            analysis,
        ),
        patch(
            "rag_graphs.research_graph.graph.app",
            graph_app,
        ),
        patch.object(svc, "_set_progress"),
        patch.object(svc, "_should_stop", return_value=False),
    ):
        out = svc._run_deep("job-1", "AAPL")

    assert out["report_id"] == 88
    assert out["continued_from_core"] is True
    assert out["source_core_report_id"] == 7
    analysis._continue_deep_from_core.assert_called_once()
    graph_app.stream.assert_not_called()


def test_run_deep_falls_back_to_full_graph_without_same_day_core():
    from services.job_queue_service import JobQueueService

    JobQueueService._instance = None
    svc = JobQueueService()
    graph_app = MagicMock()
    graph_app.stream.return_value = [
        {"gather_prices": {"live_price": 1.0}},
        {"persist": {"report_id": 3, "rating": "HOLD", "score": 5}},
    ]

    with (
        patch(
            "services.report_service.ReportService.get_same_day_core_report",
            return_value=None,
        ),
        patch(
            "rag_graphs.research_graph.graph.app",
            graph_app,
        ),
        patch.object(svc, "_set_progress"),
        patch.object(svc, "_should_stop", return_value=False),
    ):
        out = svc._run_deep("job-2", "MSFT")

    assert out["report_id"] == 3
    assert out.get("continued_from_core") is None
    graph_app.stream.assert_called_once()