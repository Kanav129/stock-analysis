from evals.decision_scoring.street_map import (
    acceptable_tags,
    tag_within_tolerance,
    target_within_tolerance,
    upside_pct,
)


def test_buy_accepts_buy_and_accumulate():
    assert acceptable_tags("buy") == {"BUY", "ACCUMULATE"}
    assert tag_within_tolerance("ACCUMULATE", "buy")
    assert not tag_within_tolerance("HOLD", "buy")


def test_hold_accepts_neighbors():
    assert "HOLD" in acceptable_tags("hold")
    assert tag_within_tolerance("REDUCE", "hold")


def test_target_tolerance():
    assert target_within_tolerance(320.0, 322.8) is True
    assert target_within_tolerance(200.0, 322.8) is False
    assert target_within_tolerance(None, 322.8) is None


def test_upside_pct():
    assert abs(upside_pct(100.0, 115.0) - 15.0) < 1e-6
