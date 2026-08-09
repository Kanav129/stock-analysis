"""Unit tests for deep-analysis priors markdown."""
from services.analysis_knowledge_service import (
    build_priors_markdown,
    driver_overlap,
    factor_distance,
    format_case_line,
)


def test_factor_distance_and_driver_overlap():
    a = {"value": 40, "growth": 60, "quality": 50, "momentum": 70, "low_risk": 40, "sentiment": 55}
    b = {"value": 42, "growth": 58, "quality": 50, "momentum": 72, "low_risk": 40, "sentiment": 55}
    assert factor_distance(a, b) < 5
    assert factor_distance(a, {}) == 999.0
    assert driver_overlap(["AI demand surge"], ["AI demand cools"]) >= 1
    assert driver_overlap(["margin expansion"], ["rate cuts"]) == 0


def test_build_priors_empty():
    md = build_priors_markdown(same_ticker=[], similar=[], aggregates=[])
    assert "## Historical performance priors" in md
    assert "Insufficient history" in md


def test_build_priors_rich_history():
    case = {
        "ticker": "AAPL",
        "rated_at": "2024-01-02T00:00:00+00:00",
        "rating": "BUY",
        "score": 48,
        "return_5d": 0.03,
        "return_20d": -0.02,
        "direction_hit_5d": True,
        "direction_hit_20d": False,
    }
    aggs = [
        {
            "horizon": "5d",
            "slice_key": "score_band=40_70",
            "n": 12,
            "hit_rate": 0.58,
            "avg_return": 0.01,
            "median_return": 0.008,
        }
    ]
    md = build_priors_markdown(
        same_ticker=[case],
        similar=[{**case, "ticker": "MSFT"}],
        aggregates=aggs,
    )
    assert "### Same ticker" in md
    assert "### Similar cases" in md
    assert "### Aggregate calibration" in md
    assert "AAPL" in md
    assert "MSFT" in md
    assert "calibrate conviction" in md.lower()


def test_build_priors_thin_aggregates():
    md = build_priors_markdown(
        same_ticker=[
            {
                "ticker": "NVDA",
                "rated_at": "2024-06-01",
                "rating": "BUY",
                "score": 50,
                "return_5d": 0.01,
                "return_20d": None,
                "direction_hit_5d": True,
                "direction_hit_20d": None,
            }
        ],
        similar=[],
        aggregates=[
            {
                "horizon": "5d",
                "slice_key": "rating=BUY",
                "n": 3,
                "hit_rate": 0.33,
                "avg_return": -0.01,
                "median_return": 0.0,
            }
        ],
    )
    assert "thin" in md.lower()
    assert format_case_line(
        {
            "ticker": "NVDA",
            "rated_at": "2024-06-01",
            "rating": "BUY",
            "score": 50,
            "return_5d": 0.01,
            "return_20d": None,
            "direction_hit_5d": True,
            "direction_hit_20d": None,
        }
    ).startswith("- NVDA")


def test_build_priors_respects_max_chars():
    cases = [
        {
            "ticker": f"T{i}",
            "rated_at": "2024-01-01",
            "rating": "BUY",
            "score": 40 + i,
            "return_5d": 0.01,
            "return_20d": 0.02,
            "direction_hit_5d": True,
            "direction_hit_20d": True,
        }
        for i in range(5)
    ]
    md = build_priors_markdown(
        same_ticker=cases,
        similar=cases,
        aggregates=[
            {
                "horizon": "20d",
                "slice_key": "score_band=40_70",
                "n": 25,
                "hit_rate": 0.5,
                "avg_return": 0.0,
                "median_return": 0.0,
            }
        ],
        max_chars=180,
    )
    assert len(md) <= 180
    assert md.endswith("...")
