from unittest.mock import MagicMock, patch

from rag_graphs.research_graph.nodes.synthesize_decision import (
    build_decision_context,
    synthesize_decision,
)


def test_build_decision_context_includes_portfolio_block():
    ctx = build_decision_context(
        ticker="AAPL",
        live_price=190.0,
        factor_scores={"value": 50, "growth": 60, "quality": 55, "momentum": 40, "low_risk": 50, "sentiment": 45},
        sections={"fundamentals": "Fund md", "news": "News md", "sentiment": "Sent md"},
        portfolio_markdown="## Personal Portfolio\n- Total value: $1.00 · 1 position(s)",
    )
    assert "## Personal Portfolio" in ctx
    assert "Total value: $1.00" in ctx
    assert "## Live Price" in ctx


def _base_state():
    return {
        "ticker": "AAPL",
        "live_price": 100.0,
        "fundamental_data": {},
        "market_data": {},
        "sentiment_data": {},
        "factor_scores": {
            "value": 50, "growth": 50, "quality": 50,
            "momentum": 50, "low_risk": 50, "sentiment": 50,
        },
        "sections_markdown": {},
    }


def _decision_mock(**overrides):
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
    for k, v in overrides.items():
        setattr(decision, k, v)
    return decision


@patch("config.llm_config.get_analysis_llm")
@patch(
    "rag_graphs.research_graph.nodes.synthesize_decision.portfolio_markdown_for",
    return_value="## Personal Portfolio\n- Analyzing AAPL: **held**",
)
def test_synthesize_decision_passes_portfolio_to_llm(mock_port, mock_llm):
    decision = _decision_mock(rating="HOLD", score=5, reasoning="ok", key_drivers=["a"],
                              supporting_headlines=["h"], position_note="Trim if over 15%.", posture="held")

    structured = MagicMock()
    structured.invoke.return_value = decision
    structured.return_value = decision
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    mock_llm.return_value = llm

    out = synthesize_decision(_base_state())  # type: ignore[arg-type]
    mock_port.assert_called_once_with("AAPL")
    call = structured.invoke.call_args or structured.call_args
    assert call is not None
    assert "## Personal Portfolio" in str(call.args[0])
    assert out["rating"] == "HOLD"


@patch("config.llm_config.resolve_env_fallback_models", return_value=[])
@patch("config.llm_config.resolve_research_model", return_value="deepseek/deepseek-v4-flash")
@patch("config.llm_config.resolve_analysis_model", return_value="openai/gpt-4o")
@patch("config.llm_config.resolve_analysis_fallbacks", return_value=["deepseek/deepseek-v4-flash"])
@patch("config.llm_config._chat_llm")
@patch("config.llm_config.get_analysis_llm")
@patch(
    "rag_graphs.research_graph.nodes.synthesize_decision.portfolio_markdown_for",
    return_value="## Personal Portfolio\n- Analyzing AAPL: **held**",
)
def test_synthesize_decision_retries_primary_then_falls_back(
    mock_port, mock_analysis_llm, mock_chat_llm, mock_fb, mock_analysis_model, mock_research_model, mock_env
):
    region_err = Exception(
        "Error code: 403 - {'error': {'message': 'This model is not available in your region.', 'code': 403}}"
    )
    analysis_structured = MagicMock()
    analysis_structured.side_effect = region_err
    analysis_structured.invoke.side_effect = region_err
    analysis_llm = MagicMock()
    analysis_llm.with_structured_output.return_value = analysis_structured
    mock_analysis_llm.return_value = analysis_llm

    fallback = _decision_mock(reasoning="fallback ok")
    research_structured = MagicMock()
    research_structured.return_value = fallback
    research_structured.invoke.return_value = fallback
    research_llm = MagicMock()
    research_llm.with_structured_output.return_value = research_structured
    mock_chat_llm.return_value = research_llm

    out = synthesize_decision(_base_state())  # type: ignore[arg-type]

    assert mock_analysis_llm.call_count == 2
    mock_chat_llm.assert_called_once_with("deepseek/deepseek-v4-flash", 0.25)
    assert out["rating"] == "BUY"
    assert out["score"] == 42
    assert out["model"] == "deepseek/deepseek-v4-flash"
    assert "Decision generation failed" not in out["reasoning"]


@patch("config.llm_config.resolve_env_fallback_models", return_value=[])
@patch("config.llm_config.resolve_research_model", return_value="deepseek/deepseek-v4-flash")
@patch("config.llm_config.resolve_analysis_model", return_value="openai/gpt-4o")
@patch("config.llm_config.resolve_analysis_fallbacks", return_value=["deepseek/deepseek-v4-flash"])
@patch("config.llm_config.get_research_llm")
@patch("config.llm_config.get_analysis_llm")
@patch(
    "rag_graphs.research_graph.nodes.synthesize_decision.portfolio_markdown_for",
    return_value="## Personal Portfolio\n- Analyzing AAPL: **held**",
)
def test_synthesize_decision_recovers_on_primary_retry(
    mock_port, mock_analysis_llm, mock_research_llm, mock_fb, mock_analysis_model, mock_research_model, mock_env
):
    region_err = Exception("Error code: 403 - region")
    recovered = _decision_mock(rating="ACCUMULATE", score=28, reasoning="retry ok")

    analysis_structured = MagicMock()
    analysis_structured.side_effect = [region_err, recovered]
    analysis_llm = MagicMock()
    analysis_llm.with_structured_output.return_value = analysis_structured
    mock_analysis_llm.return_value = analysis_llm

    out = synthesize_decision(_base_state())  # type: ignore[arg-type]

    assert mock_analysis_llm.call_count == 2
    mock_research_llm.assert_not_called()
    assert out["rating"] == "ACCUMULATE"
    assert out["score"] == 28
    assert out["model"] == "openai/gpt-4o"


@patch("config.llm_config.resolve_env_fallback_models", return_value=[])
@patch("config.llm_config.resolve_research_model", return_value="deepseek/deepseek-v4-flash")
@patch("config.llm_config.resolve_analysis_model", return_value="openai/gpt-4o")
@patch("config.llm_config.resolve_analysis_fallbacks", return_value=["deepseek/deepseek-v4-flash"])
@patch("config.llm_config._chat_llm")
@patch("config.llm_config.get_analysis_llm")
@patch(
    "rag_graphs.research_graph.nodes.synthesize_decision.portfolio_markdown_for",
    return_value="## Personal Portfolio\n- Analyzing AAPL: **held**",
)
def test_synthesize_decision_failure_sets_decision_ok_false_not_hold(
    mock_port, mock_analysis_llm, mock_chat_llm, mock_fb, mock_analysis_model, mock_research_model, mock_env
):
    failure = RuntimeError("decision providers unavailable")

    analysis_structured = MagicMock()
    analysis_structured.side_effect = failure
    analysis_structured.invoke.side_effect = failure
    analysis_llm = MagicMock()
    analysis_llm.with_structured_output.return_value = analysis_structured
    mock_analysis_llm.return_value = analysis_llm

    research_structured = MagicMock()
    research_structured.side_effect = failure
    research_structured.invoke.side_effect = failure
    research_llm = MagicMock()
    research_llm.with_structured_output.return_value = research_structured
    mock_chat_llm.return_value = research_llm

    out = synthesize_decision(_base_state())  # type: ignore[arg-type]

    assert mock_analysis_llm.call_count == 2
    mock_chat_llm.assert_called_once_with("deepseek/deepseek-v4-flash", 0.25)
    assert out.get("decision_ok") is False
    assert out.get("rating") is None
    assert out.get("score") is None
    assert out.get("error_message")
    assert "HOLD" not in str(out.get("rating"))
