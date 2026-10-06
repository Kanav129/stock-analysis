from datetime import datetime, timezone

from config.report_config import (
    annual_revenue_growth_pct,
    apply_previous_fundamentals,
    compute_dimension_alignment,
    compute_factor_scores,
    fundamentals_from_inputs,
    inputs_have_real_fundamentals,
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


def test_annual_growth_unknown_is_none_not_zero():
    assert annual_revenue_growth_pct([]) is None
    assert annual_revenue_growth_pct([], yf_revenue_growth="n/a") is None
    assert annual_revenue_growth_pct([], yf_revenue_growth=0) == 0.0


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


def test_unknown_fundamentals_score_neutral_and_flag_missing():
    scores = compute_factor_scores(
        {
            "overview": {"forward_pe": None, "beta": None},
            "revenue_growth_pct": None,
            "gross_margin_pct": None,
            "fcf_margin_pct": None,
            "cash_exceeds_debt": None,
        },
        {},
        {},
    )
    assert scores["growth"] == 50
    assert scores["quality"] == 50
    assert scores["value"] == 50
    assert scores["low_risk"] == 50
    assert scores["_inputs"]["revenue_growth_pct"] is None
    assert scores["_inputs"]["gross_margin_pct"] is None
    assert "as_of" not in scores["_inputs"]
    for key in (
        "forward_pe",
        "beta",
        "revenue_growth_pct",
        "gross_margin_pct",
        "fcf_margin_pct",
        "cash_exceeds_debt",
    ):
        assert key in scores["data_missing"]
    alignment = compute_dimension_alignment(scores, "BUY")
    assert "data_missing" not in alignment["supporting"]
    assert "data_missing" not in alignment["conflicting"]


def test_measured_zero_growth_and_margins_still_score_low():
    scores = compute_factor_scores(
        {
            "overview": {"forward_pe": 18.0, "beta": 1.1},
            "revenue_growth_pct": 0,
            "gross_margin_pct": 0,
            "fcf_margin_pct": 0,
            "cash_exceeds_debt": False,
        },
        {},
        {},
    )
    assert scores["growth"] == 0
    assert scores["quality"] == 0
    assert "data_missing" not in scores


def test_zero_default_snapshot_is_not_reusable():
    zeros = {
        "forward_pe": None,
        "beta": None,
        "revenue_growth_pct": 0,
        "gross_margin_pct": 0,
        "fcf_margin_pct": 0,
        "cash_exceeds_debt": False,
    }
    assert inputs_have_real_fundamentals(zeros) is False
    merged = apply_previous_fundamentals(
        {
            "overview": {"forward_pe": None, "beta": None},
            "revenue_growth_pct": None,
            "gross_margin_pct": None,
            "fcf_margin_pct": None,
            "cash_exceeds_debt": None,
        },
        zeros,
        "2026-09-01",
    )
    assert merged.get("revenue_growth_pct") is None
    assert merged.get("fundamentals_reused") is not True


def test_failed_fetch_reuses_last_good_numbers_with_their_date():
    current = {
        "overview": {"forward_pe": None, "beta": None, "sector": "Technology"},
        "revenue_growth_pct": None,
        "gross_margin_pct": None,
        "fcf_margin_pct": None,
        "cash_exceeds_debt": None,
    }
    previous = {
        "forward_pe": 32.4,
        "beta": 1.68,
        "revenue_growth_pct": 55.0,
        "gross_margin_pct": 75.0,
        "fcf_margin_pct": 40.0,
        "cash_exceeds_debt": True,
        "as_of": "2026-09-29",
    }
    merged = apply_previous_fundamentals(current, previous, "2026-09-29")
    scores = compute_factor_scores(merged, {}, {})
    assert merged["fundamentals_carried_forward"] is True
    assert scores["growth"] == 100
    assert scores["quality"] == 100
    assert scores["value"] == 50  # P/E 32.4 is in the 25–40 band
    assert scores["_inputs"]["as_of"] == "2026-09-29"
    assert scores["_inputs"]["forward_pe"] == 32.4
    assert scores["_inputs"]["gross_margin_pct"] == 75.0
    assert "data_missing" not in scores


def test_partial_fetch_keeps_today_and_dates_the_reused_field():
    current = {
        "overview": {"forward_pe": 20.0, "beta": 1.2},
        "revenue_growth_pct": None,
        "gross_margin_pct": 60.0,
        "fcf_margin_pct": 15.0,
        "cash_exceeds_debt": True,
    }
    previous = {
        "forward_pe": 99.0,
        "revenue_growth_pct": 22.5,
        "gross_margin_pct": 10.0,
        "fcf_margin_pct": 1.0,
        "cash_exceeds_debt": False,
    }
    merged = apply_previous_fundamentals(current, previous, "2026-09-01")
    scores = compute_factor_scores(merged, {}, {})
    today = datetime.now(timezone.utc).date().isoformat()
    assert merged["overview"]["forward_pe"] == 20.0
    assert merged["revenue_growth_pct"] == 22.5
    assert merged["gross_margin_pct"] == 60.0
    assert scores["growth"] == 75
    assert scores["_inputs"]["as_of"] == today
    assert scores["_inputs"]["reused_as_of"] == "2026-09-01"
    assert "revenue_growth_pct" in scores["_inputs"]["reused_fields"]


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
