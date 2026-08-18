from unittest.mock import MagicMock, patch

from rag_graphs.research_graph.nodes.synthesize_decision import (
    DECISION_ENABLE_THINKING,
    DECISION_TEMPERATURE,
    DecisionOutput,
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


def _decision(**overrides) -> DecisionOutput:
    payload = {
        "rating": "BUY",
        "score": 42,
        "reasoning": "ok",
        "key_drivers": ["momentum"],
        "supporting_headlines": ["headline"],
        "entry": None,
        "stop": None,
        "target": None,
        "position_note": "Add modestly.",
        "posture": "add",
    }
    payload.update(overrides)
    return DecisionOutput(**payload)


def _fc_llm(decision: DecisionOutput) -> MagicMock:
    structured = MagicMock()
    structured.return_value = decision
    structured.invoke.return_value = decision
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


@patch("rag_graphs.research_graph.nodes.synthesize_decision._record_usage")
@patch("rag_graphs.research_graph.nodes.synthesize_decision.resolve_analysis_model", return_value="qwen3.8-max")
@patch("rag_graphs.research_graph.nodes.synthesize_decision._chat_llm")
@patch(
    "rag_graphs.research_graph.nodes.synthesize_decision.portfolio_markdown_for",
    return_value="## Personal Portfolio\n- Analyzing AAPL: **held**",
)
def test_synthesize_decision_passes_portfolio_to_llm(mock_port, mock_chat_llm, mock_model, mock_usage):
    assert DECISION_ENABLE_THINKING is False
    decision = _decision(
        rating="HOLD",
        score=5,
        reasoning="ok",
        key_drivers=["a"],
        supporting_headlines=["h"],
        position_note="Trim if over 15%.",
        posture="held",
    )
    llm = _fc_llm(decision)
    mock_chat_llm.return_value = llm

    out = synthesize_decision(_base_state())  # type: ignore[arg-type]
    mock_port.assert_called_once_with("AAPL")
    mock_chat_llm.assert_called_with(
        "qwen3.8-max",
        DECISION_TEMPERATURE,
        enable_thinking=False,
    )
    structured = llm.with_structured_output.return_value
    call = structured.invoke.call_args or structured.call_args
    assert call is not None
    assert "## Personal Portfolio" in str(call.args[0])
    assert out["rating"] == "HOLD"
    assert out["score"] == 5
    llm.invoke.assert_not_called()


@patch("rag_graphs.research_graph.nodes.synthesize_decision._record_usage")
@patch("rag_graphs.research_graph.nodes.synthesize_decision._fallback_chain", return_value=["deepseek/deepseek-v4-flash"])
@patch("rag_graphs.research_graph.nodes.synthesize_decision.resolve_analysis_model", return_value="openai/gpt-4o")
@patch("rag_graphs.research_graph.nodes.synthesize_decision._chat_llm")
@patch(
    "rag_graphs.research_graph.nodes.synthesize_decision.portfolio_markdown_for",
    return_value="## Personal Portfolio\n- Analyzing AAPL: **held**",
)
def test_synthesize_decision_retries_primary_then_falls_back(
    mock_port, mock_chat_llm, mock_analysis_model, mock_fb, mock_usage
):
    region_err = Exception("Error code: 403 - region unavailable")
    primary_structured = MagicMock()
    primary_structured.side_effect = region_err
    primary_structured.invoke.side_effect = region_err
    primary_llm = MagicMock()
    primary_llm.with_structured_output.return_value = primary_structured

    fallback = _decision(reasoning="fallback ok")
    fallback_llm = _fc_llm(fallback)
    mock_chat_llm.side_effect = [primary_llm, primary_llm, fallback_llm]

    out = synthesize_decision(_base_state())  # type: ignore[arg-type]

    assert mock_chat_llm.call_count == 3
    last_call = mock_chat_llm.call_args_list[-1]
    assert last_call.args[0] == "deepseek/deepseek-v4-flash"
    assert last_call.kwargs.get("enable_thinking") is False
    assert out["rating"] == "BUY"
    assert out["score"] == 42
    assert out["model"] == "deepseek/deepseek-v4-flash"


@patch("rag_graphs.research_graph.nodes.synthesize_decision._record_usage")
@patch("rag_graphs.research_graph.nodes.synthesize_decision._fallback_chain", return_value=[])
@patch("rag_graphs.research_graph.nodes.synthesize_decision.resolve_analysis_model", return_value="openai/gpt-4o")
@patch("rag_graphs.research_graph.nodes.synthesize_decision._chat_llm")
@patch(
    "rag_graphs.research_graph.nodes.synthesize_decision.portfolio_markdown_for",
    return_value="## Personal Portfolio\n- Analyzing AAPL: **held**",
)
def test_synthesize_decision_recovers_on_primary_retry(
    mock_port, mock_chat_llm, mock_analysis_model, mock_fb, mock_usage
):
    region_err = Exception("Error code: 403 - region")
    recovered = _decision(rating="ACCUMULATE", score=28, reasoning="retry ok")
    structured = MagicMock()
    structured.side_effect = [region_err, recovered]
    structured.invoke.side_effect = [region_err, recovered]
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    mock_chat_llm.return_value = llm

    out = synthesize_decision(_base_state())  # type: ignore[arg-type]

    assert mock_chat_llm.call_count == 2
    assert out["rating"] == "ACCUMULATE"
    assert out["score"] == 28
    assert out["model"] == "openai/gpt-4o"


@patch("rag_graphs.research_graph.nodes.synthesize_decision._record_usage")
@patch("rag_graphs.research_graph.nodes.synthesize_decision._fallback_chain", return_value=["deepseek/deepseek-v4-flash"])
@patch("rag_graphs.research_graph.nodes.synthesize_decision.resolve_analysis_model", return_value="openai/gpt-4o")
@patch("rag_graphs.research_graph.nodes.synthesize_decision._chat_llm")
@patch(
    "rag_graphs.research_graph.nodes.synthesize_decision.portfolio_markdown_for",
    return_value="## Personal Portfolio\n- Analyzing AAPL: **held**",
)
def test_synthesize_decision_failure_sets_decision_ok_false_not_hold(
    mock_port, mock_chat_llm, mock_analysis_model, mock_fb, mock_usage
):
    failure = RuntimeError("decision providers unavailable")
    structured = MagicMock()
    structured.side_effect = failure
    structured.invoke.side_effect = failure
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    mock_chat_llm.return_value = llm

    out = synthesize_decision(_base_state())  # type: ignore[arg-type]

    assert out.get("decision_ok") is False
    assert out.get("rating") is None
    assert out.get("score") is None
    assert out.get("error_message")


@patch("rag_graphs.research_graph.nodes.synthesize_decision._record_usage")
@patch("rag_graphs.research_graph.nodes.synthesize_decision._fallback_chain", return_value=[])
@patch("rag_graphs.research_graph.nodes.synthesize_decision.resolve_analysis_model", return_value="qwen3.8-max")
@patch("rag_graphs.research_graph.nodes.synthesize_decision._chat_llm")
@patch(
    "rag_graphs.research_graph.nodes.synthesize_decision.portfolio_markdown_for",
    return_value="## Personal Portfolio\n- Analyzing AAPL: **held**",
)
def test_synthesize_decision_uses_function_calling_when_thinking_off(
    mock_port, mock_chat_llm, mock_model, mock_fb, mock_usage
):
    decision = _decision(rating="BUY", score=55, reasoning="fc path")
    llm = _fc_llm(decision)
    mock_chat_llm.return_value = llm

    out = synthesize_decision(_base_state())  # type: ignore[arg-type]

    assert out["decision_ok"] is True
    assert out["rating"] == "BUY"
    assert out["score"] == 55
    llm.with_structured_output.assert_called()
    llm.invoke.assert_not_called()
