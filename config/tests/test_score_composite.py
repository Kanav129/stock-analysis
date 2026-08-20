from config.rating_config import rating_from_score
from config.score_composite import (
    apply_action_cap,
    composite_score,
    map_level,
    weighted_raw_score,
)


def _decision(levels: dict[str, int], action: str = "hold") -> dict:
    dims = {
        key: {"bearish": ["b"], "bullish": ["u"], "score_1_to_5": level}
        for key, level in levels.items()
    }
    return {"this_week_action": action, **dims}


def test_map_level_anchors():
    assert map_level(1) == -100
    assert map_level(2) == -50
    assert map_level(3) == 0
    assert map_level(4) == 50
    assert map_level(5) == 100
    assert map_level(9) == 0


def test_all_threes_is_neutral_hold():
    score, note = composite_score(
        _decision(
            {
                "fundamental_health": 3,
                "valuation": 3,
                "this_week_setup": 3,
                "technical_momentum": 3,
                "sentiment_and_news": 3,
            },
            action="hold",
        )
    )
    assert score == 0
    assert rating_from_score(score) == "HOLD"
    assert "fund 3" in note


def test_aapl_like_mix_is_negative_hold_not_magnet():
    levels = {
        "fundamental_health": 4,
        "valuation": 2,
        "technical_momentum": 3,
        "sentiment_and_news": 3,
        "this_week_setup": 2,
    }
    raw = weighted_raw_score(levels)
    assert raw == -10
    score, _note = composite_score(_decision(levels, action="hold"))
    assert score == -10
    assert rating_from_score(score) == "HOLD"
    assert score != 34


def test_action_caps_never_inflate_mild_composite():
    levels = {
        "fundamental_health": 3,
        "valuation": 3,
        "this_week_setup": 3,
        "technical_momentum": 3,
        "sentiment_and_news": 3,
    }
    score, _ = composite_score(_decision(levels, action="strong_buy"))
    assert score == 0
    assert apply_action_cap(80, "buy") == 69
    assert apply_action_cap(80, "strong_buy") == 80
    assert apply_action_cap(-50, "strong_sell") == -70
    assert apply_action_cap(50, "accumulate") == 39
    assert apply_action_cap(40, "hold") == 40


def test_hold_action_does_not_pin_constructive_mix_to_band_edge():
    levels = {
        "fundamental_health": 4,
        "valuation": 4,
        "this_week_setup": 3,
        "technical_momentum": 3,
        "sentiment_and_news": 3,
    }
    score, _ = composite_score(_decision(levels, action="hold"))
    assert score == 25
    assert rating_from_score(score) == "ACCUMULATE"
