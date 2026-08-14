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
