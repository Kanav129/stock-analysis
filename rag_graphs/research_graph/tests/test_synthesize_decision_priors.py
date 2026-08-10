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


@patch(
    "rag_graphs.research_graph.nodes.synthesize_decision.build_decision_context",
    wraps=build_decision_context,
)
@patch("rag_graphs.research_graph.nodes.synthesize_decision._record_usage")
@patch("rag_graphs.research_graph.nodes.synthesize_decision.resolve_analysis_model", return_value="qwen3.7-max")
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
    import json
    llm = MagicMock()
    raw = MagicMock()
    raw.content = json.dumps({
        "rating": "BUY", "score": 42, "reasoning": "ok",
        "key_drivers": ["momentum"], "supporting_headlines": ["headline"],
        "entry": None, "stop": None, "target": None,
        "position_note": "Add modestly.", "posture": "add",
    })
    llm.invoke.return_value = raw
    mock_chat_llm.return_value = llm

    synthesize_decision(_base_state(report_type="deep"))  # type: ignore[arg-type]
    mock_priors.assert_called_once()
    assert mock_build.call_args.kwargs.get("priors_markdown", "").find("prior case") >= 0


@patch(
    "rag_graphs.research_graph.nodes.synthesize_decision.build_decision_context",
    wraps=build_decision_context,
)
@patch("rag_graphs.research_graph.nodes.synthesize_decision._record_usage")
@patch("rag_graphs.research_graph.nodes.synthesize_decision.resolve_analysis_model", return_value="qwen3.7-max")
@patch("rag_graphs.research_graph.nodes.synthesize_decision._chat_llm")
@patch(
    "rag_graphs.research_graph.nodes.synthesize_decision.portfolio_markdown_for",
    return_value="## Personal Portfolio\n- held",
)
@patch(
    "services.analysis_knowledge_service.analysis_knowledge_service.priors_for_deep",
    return_value="## Historical performance priors\n- prior case",
)
def test_core_skips_priors(mock_priors, mock_port, mock_chat_llm, mock_model, mock_usage, mock_build):
    import json
    llm = MagicMock()
    raw = MagicMock()
    raw.content = json.dumps({
        "rating": "BUY", "score": 42, "reasoning": "ok",
        "key_drivers": ["momentum"], "supporting_headlines": ["headline"],
        "entry": None, "stop": None, "target": None,
        "position_note": "Add modestly.", "posture": "add",
    })
    llm.invoke.return_value = raw
    mock_chat_llm.return_value = llm

    synthesize_decision(_base_state(report_type="core"))  # type: ignore[arg-type]
    mock_priors.assert_not_called()
    assert mock_build.call_args.kwargs.get("priors_markdown", "") == ""
