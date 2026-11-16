from unittest.mock import MagicMock, patch

from rag_graphs.research_graph.nodes.persist_report import persist_report


def test_persist_report_raises_on_failed_decision_without_saving():
    with (
        patch("rag_graphs.research_graph.nodes.persist_report.ReportService") as reports,
        patch("rag_graphs.research_graph.nodes.persist_report.RatingsService") as ratings,
    ):
        try:
            persist_report({
                "ticker": "MU",
                "report_type": "deep",
                "decision_ok": False,
                "error_message": "quota exhausted",
                "sections_markdown": {"flows": "*failed*"},
            })
        except RuntimeError as exc:
            assert "quota" in str(exc).lower() or "decision" in str(exc).lower()
        else:
            raise AssertionError("expected persist_report to raise")

    reports.return_value.save_report.assert_not_called()
    ratings.return_value.save_rating.assert_not_called()


def test_persist_report_saves_successful_decision():
    with (
        patch("rag_graphs.research_graph.nodes.persist_report.ReportService") as reports,
        patch("rag_graphs.research_graph.nodes.persist_report.RatingsService") as ratings,
    ):
        reports.return_value.save_report.return_value = 12
        out = persist_report({
            "ticker": "AAPL",
            "report_type": "core",
            "decision_ok": True,
            "rating": "HOLD",
            "score": 5,
            "sections_markdown": {"market": "m", "fundamentals": "f"},
            "live_price": 100.0,
            "model": "qwen3.7-max",
        })
    assert out["report_id"] == 12
    reports.return_value.save_report.assert_called_once()
    ratings.return_value.save_rating.assert_called_once()


def test_persist_report_stores_core_deep_request_on_rating():
    with (
        patch("rag_graphs.research_graph.nodes.persist_report.ReportService") as reports,
        patch("rag_graphs.research_graph.nodes.persist_report.RatingsService"),
    ):
        reports.return_value.save_report.return_value = 12
        persist_report({
            "ticker": "AAPL",
            "report_type": "core",
            "decision_ok": True,
            "rating": "HOLD",
            "score": 12,
            "sections_markdown": {"market": "m"},
            "deep_request": {
                "recommended": True,
                "reason": "Flows are the open question.",
            },
        })
    rating = reports.return_value.save_report.call_args.kwargs["rating"]
    assert rating["deep_request"]["recommended"] is True
    assert rating["deep_request"]["reason"] == "Flows are the open question."
    assert rating["deep_request"]["enqueued_by"] is None


def test_persist_deep_report_omits_deep_request():
    with (
        patch("rag_graphs.research_graph.nodes.persist_report.ReportService") as reports,
        patch("rag_graphs.research_graph.nodes.persist_report.RatingsService"),
    ):
        reports.return_value.save_report.return_value = 13
        persist_report({
            "ticker": "AAPL",
            "report_type": "deep",
            "decision_ok": True,
            "rating": "BUY",
            "score": 40,
            "sections_markdown": {"flows": "f"},
            "deep_request": {"recommended": True, "reason": "ignore"},
        })
    rating = reports.return_value.save_report.call_args.kwargs["rating"]
    assert "deep_request" not in rating


def test_rescore_keeps_existing_deep_request_audit():
    with (
        patch("rag_graphs.research_graph.nodes.persist_report.ReportService") as reports,
        patch("rag_graphs.research_graph.nodes.persist_report.RatingsService"),
    ):
        reports.return_value.get_report_by_id.return_value = {
            "rating": {
                "deep_request": {
                    "recommended": True,
                    "reason": "Lockup was open.",
                    "enqueued_by": "model",
                }
            }
        }
        persist_report({
            "ticker": "AAPL",
            "report_id": 9,
            "report_type": "core",
            "decision_ok": True,
            "rating": "HOLD",
            "score": 4,
            "sections_markdown": {},
            "deep_request": {"recommended": False, "reason": ""},
        })
    rating = reports.return_value.update_report_rating.call_args.kwargs["rating"]
    assert rating["deep_request"]["enqueued_by"] == "model"
    assert rating["deep_request"]["reason"] == "Lockup was open."
