from unittest.mock import MagicMock, patch

from rag_graphs.research_graph.nodes.debate import assemble_debate_context, debate


def test_assemble_debate_context_appends_portfolio():
    sections = {"fundamentals": "Fund text " * 50, "news": "News"}
    out = assemble_debate_context(
        sections,
        "## Personal Portfolio\n- Analyzing NVDA: **held**",
    )
    assert "## Fundamentals" in out
    assert "## Personal Portfolio" in out
    assert "NVDA" in out


@patch("rag_graphs.research_graph.nodes.debate.invoke_research_llm")
@patch(
    "rag_graphs.research_graph.nodes.debate.portfolio_markdown_for",
    return_value="## Personal Portfolio\n- held",
)
def test_debate_fetches_portfolio_context(mock_port, mock_invoke):
    """Single combined debate call still receives portfolio context."""
    resp = MagicMock(content="ok")
    mock_invoke.return_value = (resp, "qwen3.7-flash")
    debate({
        "ticker": "AAPL",
        "live_price": 1.0,
        "factor_scores": {},
        "sections_markdown": {"news": "n"},
    })  # type: ignore[arg-type]
    mock_port.assert_called_once_with("AAPL")
    assert mock_invoke.call_count == 1
    inputs = mock_invoke.call_args.args[1]
    assert "Personal Portfolio" in str(inputs)
