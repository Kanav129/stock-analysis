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


@patch("rag_graphs.research_graph.nodes.synthesize_decision.get_analysis_llm")
@patch(
    "rag_graphs.research_graph.nodes.synthesize_decision.portfolio_markdown_for",
    return_value="## Personal Portfolio\n- Analyzing AAPL: **held**",
)
def test_synthesize_decision_passes_portfolio_to_llm(mock_port, mock_llm):
    decision = MagicMock()
    decision.rating = "HOLD"
    decision.score = 5
    decision.reasoning = "ok"
    decision.key_drivers = ["a"]
    decision.supporting_headlines = ["h"]
    decision.entry = None
    decision.stop = None
    decision.target = None
    decision.position_note = "Trim if over 15%."
    decision.posture = "held"

    structured = MagicMock()
    structured.invoke.return_value = decision
    structured.return_value = decision  # LangChain may call runnable via __call__
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    mock_llm.return_value = llm

    state = {
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
    out = synthesize_decision(state)  # type: ignore[arg-type]
    mock_port.assert_called_once_with("AAPL")
    # prompt | structured_llm passes ChatPromptValue (or messages), not a raw dict
    call = structured.invoke.call_args or structured.call_args
    assert call is not None
    assert "## Personal Portfolio" in str(call.args[0])
    assert out["rating"] == "HOLD"
