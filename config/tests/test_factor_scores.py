from config.report_config import (
    annual_revenue_growth_pct,
    compute_dimension_alignment,
    compute_factor_scores,
    fundamentals_from_inputs,
)


def test_annual_growth_sorts_newest_first_rows_ascending():
    """Alpha Vantage typically returns newest fiscal year first."""
    rows = [
        {"fiscalDateEnding": "2025-09-30", "totalRevenue": "120"},
        {"fiscalDateEnding": "2024-09-30", "totalRevenue": "100"},
        {"fiscalDateEnding": "2023-09-30", "totalRevenue": "80"},
    ]
    growth = annual_revenue_growth_pct(rows)
    # 80→100 = 25%, 100→120 = 20% → avg 22.5
    assert growth == 22.5


def test_annual_growth_falls_back_to_yfinance_fraction():
    assert annual_revenue_growth_pct([], yf_revenue_growth=0.18) == 18.0


def test_compute_factor_scores_uses_growth_and_persists_inputs():
    fundamentals = {
        "overview": {"forward_pe": 18.0, "beta": 1.1},
        "revenue_growth_pct": 22.5,
        "gross_margin_pct": 55.0,
        "fcf_margin_pct": 15.0,
        "cash_exceeds_debt": True,
    }
    market = {
        "moving_averages": {
            "ema_10": 10,
            "sma_20": 9,
            "sma_50": 8,
            "sma_200": 7,
            "price_vs_ema_10_pct": 1,
            "price_vs_sma_20_pct": 1,
            "price_vs_sma_50_pct": 1,
            "price_vs_sma_200_pct": 1,
        },
        "rsi": 58,
        "macd_histogram": 0.2,
        "atr_pct": 2.0,
    }
    sentiment = {"stocktwits": {"bullish_pct": 40}}
    scores = compute_factor_scores(fundamentals, market, sentiment)
    assert scores["growth"] == 75
    assert scores["value"] == 75
    assert scores["_inputs"]["forward_pe"] == 18.0
    assert scores["_inputs"]["revenue_growth_pct"] == 22.5


def test_fundamentals_from_inputs_round_trips_for_recompute():
    inputs = {
        "forward_pe": 26.3,
        "beta": 0.9,
        "revenue_growth_pct": 12.0,
        "gross_margin_pct": 40.0,
        "fcf_margin_pct": 8.0,
        "cash_exceeds_debt": False,
    }
    fund = fundamentals_from_inputs(inputs)
    scores = compute_factor_scores(fund, {}, {})
    assert scores["value"] == 50  # PE 26.3 → 25–40 band
    assert scores["growth"] == 50  # 12%
    assert scores["_inputs"]["forward_pe"] == 26.3


def test_dimension_alignment_ignores_inputs_key():
    scores = {
        "value": 80,
        "growth": 80,
        "quality": 80,
        "momentum": 80,
        "low_risk": 80,
        "sentiment": 10,
        "_inputs": {"forward_pe": 12},
    }
    out = compute_dimension_alignment(scores, "BUY")
    assert "_inputs" not in out["supporting"]
    assert "_inputs" not in out["conflicting"]
