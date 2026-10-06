"""Weekly fundamentals gathering reads av_fundamentals and does not refresh it."""
from unittest.mock import patch

from rag_graphs.research_graph.nodes.gather_fundamentals import gather_fundamentals


class _Stock:
    info = {
        "currentPrice": 20.0,
        "sector": "Technology",
        "marketCap": 100,
        "regularMarketPrice": 20.0,
    }


class _Result:
    content = "cached fundamentals"


@patch("rag_graphs.research_graph.nodes.gather_fundamentals.invoke_research_llm")
@patch("rag_graphs.research_graph.nodes.gather_fundamentals.get_yf_ticker")
@patch("rag_graphs.research_graph.nodes.gather_fundamentals.AlphaVantageClient")
def test_gather_fundamentals_prefers_cached_av_fundamentals(mock_cls, mock_yf, mock_llm):
    snapshot = {
        "overview": {"sector": "Technology", "eps": "1.25"},
        "income_annual": [{"fiscalDateEnding": "2025-12-31", "totalRevenue": "100"}],
        "income_quarterly": [{"fiscalDateEnding": "2026-06-30", "totalRevenue": "40"}],
        "balance_annual": [],
        "balance_quarterly": [],
        "cashflow_annual": [],
        "cashflow_quarterly": [],
        "errors": {},
    }
    client = mock_cls.return_value
    client.get_financial_snapshot.return_value = snapshot
    mock_yf.return_value = _Stock()
    mock_llm.return_value = (_Result(), None)

    out = gather_fundamentals({"ticker": "AAPL", "live_price": 20.0})

    client.get_financial_snapshot.assert_called_once_with("AAPL", refresh=False)
    assert out["fundamental_data"]["av_snapshot"]["income_quarterly"][0]["totalRevenue"] == "40"
    assert "cached fundamentals" in out["sections_markdown"]["fundamentals"]
