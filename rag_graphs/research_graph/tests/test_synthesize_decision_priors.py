"""Deep analysis injects rich priors; core gets same-ticker priors only."""
from unittest.mock import MagicMock, patch

from rag_graphs.research_graph.nodes.synthesize_decision import (
    DecisionOutput,
    DimensionRating,
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


def _fc_llm() -> MagicMock:
    decision = DecisionOutput(
        bearish_factors=["valuation", "extension"],
        bullish_factors=["franchise", "cash flow"],
        fundamental_health=DimensionRating(bearish=["risk"], bullish=["ok"], score_1_to_5=5),
        valuation=DimensionRating(bearish=["risk"], bullish=["ok"], score_1_to_5=4),
        technical_momentum=DimensionRating(bearish=["risk"], bullish=["ok"], score_1_to_5=3),
        sentiment_and_news=DimensionRating(bearish=["risk"], bullish=["ok"], score_1_to_5=3),
        this_week_setup=DimensionRating(bearish=["risk"], bullish=["ok"], score_1_to_5=4),
        this_week_action="buy",
        reasoning="ok",
        key_drivers=["momentum"],
        supporting_headlines=["headline"],
        entry=None,
        stop=None,
        target=None,
        position_note="Add modestly.",
        posture="add",
    )
    structured = MagicMock()
    structured.return_value = decision
    structured.invoke.return_value = decision
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


@patch(
    "rag_graphs.research_graph.nodes.synthesize_decision.build_decision_context",
    wraps=build_decision_context,
)
@patch("rag_graphs.research_graph.nodes.synthesize_decision._record_usage")
@patch("rag_graphs.research_graph.nodes.synthesize_decision.resolve_analysis_model", return_value="qwen3.8-max")
@patch("rag_graphs.research_graph.nodes.synthesize_decision._chat_llm")
@patch(
    "rag_graphs.research_graph.nodes.synthesize_decision.portfolio_markdown_for",
    return_value="## Personal Portfolio\n- held",
)
@patch(
    "services.analysis_knowledge_service.analysis_knowledge_service.priors_for_deep",
    return_value="## Historical performance priors\n- prior case",
)
def test_deep_includes_priors(mock_priors, mock_port, mock_chat_llm, mock_model, mock_usage, mock_build):
    mock_chat_llm.return_value = _fc_llm()

    synthesize_decision(_base_state(report_type="deep"))  # type: ignore[arg-type]
    mock_priors.assert_called_once()
    assert mock_build.call_args.kwargs.get("priors_markdown", "").find("prior case") >= 0


@patch(
    "rag_graphs.research_graph.nodes.synthesize_decision.build_decision_context",
    wraps=build_decision_context,
)
@patch("rag_graphs.research_graph.nodes.synthesize_decision._record_usage")
@patch("rag_graphs.research_graph.nodes.synthesize_decision.resolve_analysis_model", return_value="qwen3.8-max")
@patch("rag_graphs.research_graph.nodes.synthesize_decision._chat_llm")
@patch(
    "rag_graphs.research_graph.nodes.synthesize_decision.portfolio_markdown_for",
    return_value="## Personal Portfolio\n- held",
)
@patch(
    "services.analysis_knowledge_service.analysis_knowledge_service.priors_for_core",
    return_value="## Historical performance priors\n- core prior",
)
def test_core_includes_same_ticker_priors(mock_priors, mock_port, mock_chat_llm, mock_model, mock_usage, mock_build):
    mock_chat_llm.return_value = _fc_llm()

    synthesize_decision(_base_state(report_type="core"))  # type: ignore[arg-type]
    mock_priors.assert_called_once()
    assert "core prior" in (mock_build.call_args.kwargs.get("priors_markdown") or "")
