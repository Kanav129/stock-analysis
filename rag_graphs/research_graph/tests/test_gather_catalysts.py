from rag_graphs.research_graph.nodes.gather_catalysts import format_catalysts_markdown


def test_format_catalysts_markdown_includes_earnings_street_peers():
    md = format_catalysts_markdown(
        earnings="2026-08-20",
        recs="buy 12, hold 4",
        target="Mean 240 (+6.7% vs live); high 280; low 200",
        peers=["AMD", "AVGO"],
    )
    assert "## Earnings / Street" in md
    assert "2026-08-20" in md
    assert "240" in md
    assert "AMD" in md
    assert "AVGO" in md
