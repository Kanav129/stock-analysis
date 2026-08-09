"""Deep analysis injects historical priors; core does not."""
from unittest.mock import MagicMock, patch

from rag_graphs.research_graph.nodes.synthesize_decision import (
    build_decision_context,
    synthesize_decision,
)


def test_build_decision_context_appends_priors():
    ctx = build_decision_context(
        ticker="AAPL",
        live_price=190.0,
        factor_scores={
            "value": 50,
            "growth": 60,
            "quality": 55,
            "momentum": 40,
            "low_risk": 50,
            "sentiment": 45,
        },
        sections={"fundamentals": "Fund"},
        portfolio_markdown="## Personal Portfolio\n- none",
        priors_markdown="## Historical performance priors\n- sample",
    )
    assert "## Historical performance priors" in ctx
    assert "sample" in ctx


def _base_state(**overrides):
    state = {
        "ticker": "AAPL",
        "report_type": "core",
        "live_price": 100.0,
        "fundamental_data": {},
        "market_data": {},
        "sentiment_data": {},
        "factor_scores": {
            "value": 50,
            "growth": 50,
            "quality": 50,
            "momentum": 50,
            "low_risk": 50,
            "sentiment": 50,
        },
        "sections_markdown": {},
    }
    state.update(overrides)
    return state


def _decision_mock():
    decision = MagicMock()
    decision.rating = "BUY"
    decision.score = 42
    decision.reasoning = "ok"
    decision.key_drivers = ["momentum"]
    decision.supporting_headlines = ["headline"]
    decision.entry = None
    decision.stop = None
    decision.target = None
    decision.position_note = "Add modestly."
    decision.posture = "add"
    return decision


@patch(
    "rag_graphs.research_graph.nodes.synthesize_decision.build_decision_context",
    wraps=build_decision_context,
)
@patch("config.llm_config.get_analysis_llm")
@patch(
    "rag_graphs.research_graph.nodes.synthesize_decision.portfolio_markdown_for",
    return_value="## Personal Portfolio\n- held",
)
@patch(
    "services.analysis_knowledge_service.analysis_knowledge_service.priors_for_deep",
    return_value="## Historical performance priors\n- prior case",
)
def test_deep_includes_priors(mock_priors, mock_port, mock_llm, mock_build):
    structured = MagicMock()
    structured.invoke.return_value = _decision_mock()
    structured.return_value = _decision_mock()
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    mock_llm.return_value = llm

    synthesize_decision(_base_state(report_type="deep"))  # type: ignore[arg-type]
    mock_priors.assert_called_once()
    assert mock_build.call_args.kwargs.get("priors_markdown", "").find("prior case") >= 0


@patch(
    "rag_graphs.research_graph.nodes.synthesize_decision.build_decision_context",
    wraps=build_decision_context,
)
@patch("config.llm_config.get_analysis_llm")
@patch(
    "rag_graphs.research_graph.nodes.synthesize_decision.portfolio_markdown_for",
    return_value="## Personal Portfolio\n- held",
)
@patch(
    "services.analysis_knowledge_service.analysis_knowledge_service.priors_for_deep",
    return_value="## Historical performance priors\n- prior case",
)
def test_core_skips_priors(mock_priors, mock_port, mock_llm, mock_build):
    structured = MagicMock()
    structured.invoke.return_value = _decision_mock()
    structured.return_value = _decision_mock()
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    mock_llm.return_value = llm

    synthesize_decision(_base_state(report_type="core"))  # type: ignore[arg-type]
    mock_priors.assert_not_called()
    assert mock_build.call_args.kwargs.get("priors_markdown", "") == ""
