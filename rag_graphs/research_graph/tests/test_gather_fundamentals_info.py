"""Yahoo info mapping: Invalid Crumb must not become 0% fundamentals."""
from unittest.mock import MagicMock, patch

from config.report_config import apply_previous_fundamentals, compute_factor_scores
from rag_graphs.research_graph.nodes.gather_fundamentals import gather_fundamentals


class _CrumbFailure:
    @property
    def info(self):
        raise RuntimeError(
            'HTTP Error 401: {"finance":{"error":{"description":"Invalid Crumb"}}}'
        )


class _Quote:
    def __init__(self, info):
        self.info = info


def _av_client(snapshot):
    client = MagicMock()
    client.get_financial_snapshot.return_value = snapshot
    return client


@patch(
    "rag_graphs.research_graph.nodes.gather_fundamentals.invoke_research_llm",
    return_value=(MagicMock(content="ok"), "model"),
)
@patch("rag_graphs.research_graph.nodes.gather_fundamentals.AlphaVantageClient")
@patch("rag_graphs.research_graph.nodes.gather_fundamentals.get_yf_ticker")
def test_invalid_crumb_leaves_metrics_empty_and_previous_fixture_still_scores(
    mock_ticker, mock_av, _llm
):
    mock_ticker.return_value = _CrumbFailure()
    mock_av.return_value = _av_client(
        {"overview": {}, "income_annual": [], "errors": {"overview": "rate_limit"}}
    )

    result = gather_fundamentals({"ticker": "NVDA", "live_price": 180.0})
    fund = result["fundamental_data"]
    assert fund["overview"]["forward_pe"] is None
    assert fund["overview"]["beta"] is None
    assert fund["revenue_growth_pct"] is None
    assert fund["gross_margin_pct"] is None
    assert fund["fcf_margin_pct"] is None
    assert fund["cash_exceeds_debt"] is None

    # Today's fetch failed, but a prior real snapshot must still flow through.
    previous = {
        "forward_pe": 32.4,
        "beta": 1.68,
        "revenue_growth_pct": 55.0,
        "gross_margin_pct": 75.0,
        "fcf_margin_pct": 40.0,
        "cash_exceeds_debt": True,
        "as_of": "2026-09-29",
    }
    merged = apply_previous_fundamentals(fund, previous, "2026-09-29")
    scores = compute_factor_scores(merged, {}, {})
    assert scores["growth"] == 100
    assert scores["quality"] == 100
    assert scores["_inputs"]["forward_pe"] == 32.4
    assert scores["_inputs"]["gross_margin_pct"] == 75.0
    assert scores["_inputs"]["as_of"] == "2026-09-29"
    assert "data_missing" not in scores


@patch(
    "rag_graphs.research_graph.nodes.gather_fundamentals.invoke_research_llm",
    return_value=(MagicMock(content="ok"), "model"),
)
@patch("rag_graphs.research_graph.nodes.gather_fundamentals.AlphaVantageClient")
@patch("rag_graphs.research_graph.nodes.gather_fundamentals.get_yf_ticker")
def test_real_yahoo_info_fields_flow_into_fundamentals(mock_ticker, mock_av, _llm):
    mock_ticker.return_value = _Quote(
        {
            "forwardPE": 32.5,
            "beta": 1.7,
            "grossMargins": 0.75,
            "revenueGrowth": 0.55,
            "operatingCashflow": 50,
            "capitalExpenditure": 10,
            "totalRevenue": 100,
            "totalCash": 20,
            "totalDebt": 5,
            "currentPrice": 180,
            "sector": "Technology",
        }
    )
    mock_av.return_value = _av_client(
        {"overview": {}, "income_annual": [], "errors": {}}
    )

    result = gather_fundamentals({"ticker": "NVDA"})
    fund = result["fundamental_data"]
    assert fund["overview"]["forward_pe"] == 32.5
    assert fund["overview"]["beta"] == 1.7
    assert fund["overview"]["sector"] == "Technology"
    assert fund["revenue_growth_pct"] == 55.0
    assert fund["gross_margin_pct"] == 75.0
    assert fund["fcf_margin_pct"] == 40.0
    assert fund["cash_exceeds_debt"] is True
    scores = compute_factor_scores(fund, {}, {})
    assert scores["growth"] == 100
    assert scores["quality"] == 100
    assert "data_missing" not in scores
