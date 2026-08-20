from config.rating_config import rating_from_score, reconcile_horizon_decision


def test_rating_from_score_cutovers():
    assert rating_from_score(12) == "HOLD"
    assert rating_from_score(15) == "HOLD"
    assert rating_from_score(16) == "ACCUMULATE"
    assert rating_from_score(32) == "ACCUMULATE"
    assert rating_from_score(39) == "ACCUMULATE"
    assert rating_from_score(40) == "BUY"
    assert rating_from_score(70) == "STRONG_BUY"
    assert rating_from_score(-15) == "HOLD"
    assert rating_from_score(-16) == "REDUCE"
    assert rating_from_score(-39) == "REDUCE"
    assert rating_from_score(-40) == "SELL"
    assert rating_from_score(-69) == "SELL"
    assert rating_from_score(-70) == "STRONG_SELL"


def test_horizon_does_not_snap_to_band_midpoint():
    rating, score, entry = reconcile_horizon_decision(
        rating="BUY",
        score=62,
        entry=52.5,
        live_price=53.26,
        posture="Hold core position, accumulate on dips.",
        position_note="Wait for a pullback",
    )
    assert rating == "ACCUMULATE"
    assert score == 38
    assert entry is not None and entry < 53.26
