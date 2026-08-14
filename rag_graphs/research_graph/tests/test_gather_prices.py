from unittest.mock import patch

from rag_graphs.research_graph.nodes.gather_prices import gather_prices


@patch("rag_graphs.research_graph.nodes.gather_prices.get_market_data")
def test_gather_prices_writes_market_markdown(mock_get):
    mock_get.return_value = (
        {
            "live_price": 50.0,
            "rsi": 55.0,
            "rsi_regime": "neutral",
            "macd_histogram": 0.1,
            "macd_line": 0.2,
            "macd_signal": 0.1,
            "atr": 1.0,
            "atr_pct": 2.0,
            "volume_latest": 100,
            "volume_avg_20d": 80,
            "volume_ratio": 1.25,
            "moving_averages": {
                "ema_10": 49,
                "sma_20": 48,
                "sma_50": 47,
                "sma_200": 40,
                "price_vs_ema_10_pct": 2,
                "price_vs_sma_20_pct": 4,
                "price_vs_sma_50_pct": 6,
                "price_vs_sma_200_pct": 25,
                "bullish_alignment": True,
            },
            "price_source": "stock_data",
            "daily_bar_count": 120,
        },
        50.0,
        None,
    )
    out = gather_prices({"ticker": "IMAX", "sections_markdown": {}, "errors": []})
    assert out["live_price"] == 50.0
    md = out["sections_markdown"]["market"]
    assert "## Market / Technicals" in md
    assert "RSI" in md
    assert "50" in md


@patch("rag_graphs.research_graph.nodes.gather_prices.get_market_data")
def test_gather_prices_appends_error_without_market_section(mock_get):
    mock_get.return_value = (None, None, "No price data for ZZ")
    out = gather_prices({"ticker": "ZZ", "sections_markdown": {}, "errors": []})
    assert "No price data" in out["errors"][0]
    assert "sections_markdown" not in out or "market" not in out.get("sections_markdown", {})
