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


@patch("rag_graphs.research_graph.nodes.debate.get_research_llm")
@patch(
    "rag_graphs.research_graph.nodes.debate.portfolio_markdown_for",
    return_value="## Personal Portfolio\n- held",
)
def test_debate_fetches_portfolio_context(mock_port, mock_llm):
    """Minimum-bar: portfolio fetched; ≥2 invokes (neutral + manager) see it."""
    resp = MagicMock(content="ok")
    chain = MagicMock()
    chain.invoke.return_value = resp
    prompt_obj = MagicMock()
    prompt_obj.__or__ = MagicMock(return_value=chain)
    mock_llm.return_value = MagicMock()
    with patch(
        "rag_graphs.research_graph.nodes.debate.ChatPromptTemplate.from_messages",
        return_value=prompt_obj,
    ):
        debate({
            "ticker": "AAPL",
            "live_price": 1.0,
            "factor_scores": {},
            "sections_markdown": {"news": "n"},
        })  # type: ignore[arg-type]
    mock_port.assert_called_once_with("AAPL")
    # At least two invokes (neutral + manager) should include portfolio in context
    portfolio_hits = 0
    for call in chain.invoke.call_args_list:
        payload = call.args[0] if call.args else {}
        blob = str(payload)
        if "Personal Portfolio" in blob:
            portfolio_hits += 1
    assert portfolio_hits >= 2
