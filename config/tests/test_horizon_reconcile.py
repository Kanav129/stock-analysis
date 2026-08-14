from config.rating_config import reconcile_horizon_decision


def test_buy_with_dip_posture_becomes_accumulate():
    rating, score, entry = reconcile_horizon_decision(
        rating="BUY",
        score=62,
        entry=52.5,
        live_price=53.26,
        posture="Hold core position, accumulate on dips.",
        position_note="Wait for a pullback",
    )
    assert rating == "ACCUMULATE"
    assert score <= 40
    assert entry is not None and entry < 53.26


def test_buy_at_live_price_stays_buy():
    rating, score, entry = reconcile_horizon_decision(
        rating="BUY",
        score=58,
        entry=225.3,
        live_price=225.3,
        posture="Add modestly on confirmation.",
        position_note="Buy near last.",
    )
    assert rating == "BUY"
    assert score == 58
    assert entry == 225.3


def test_buy_entry_well_below_live_becomes_accumulate():
    rating, score, entry = reconcile_horizon_decision(
        rating="BUY",
        score=55,
        entry=65.0,
        live_price=72.36,
        posture="Wait for a pullback to $62-$65.",
        position_note="Do not chase.",
    )
    assert rating in ("HOLD", "ACCUMULATE")
    assert score <= 40


def test_buy_with_null_entry_keeps_buy_at_market():
    rating, score, entry = reconcile_horizon_decision(
        rating="BUY",
        score=55,
        entry=None,
        live_price=100.0,
        posture="Add this week.",
        position_note="Market order.",
    )
    assert rating == "BUY"
    assert score == 55
    assert entry == 100.0
