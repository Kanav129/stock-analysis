"""Unit tests for rating outcome math and status helpers."""
from datetime import datetime, timezone

from services.outcome_service import (
    compute_return,
    direction_hit,
    extract_entry_price,
    forward_close,
    outcome_status,
    score_band_key,
)


def test_extract_entry_price_from_summary():
    assert extract_entry_price({"live_price": 120.5}) == 120.5
    assert extract_entry_price({}, report_live_price=99.0) == 99.0
    assert extract_entry_price({"live_price": 0}) is None
    assert extract_entry_price(None) is None


def test_compute_return():
    assert abs(compute_return(100.0, 110.0) - 0.10) < 1e-9
    assert abs(compute_return(100.0, 90.0) - (-0.10)) < 1e-9


def test_direction_hit_rules():
    assert direction_hit("BUY", 0.05) is True
    assert direction_hit("STRONG_BUY", -0.02) is False
    assert direction_hit("SELL", -0.04) is True
    assert direction_hit("REDUCE", 0.01) is False
    assert direction_hit("HOLD", 0.03) is None
    assert direction_hit("BUY", None) is None


def test_forward_close_nth_trading_day():
    closes = [
        (datetime(2024, 1, 2, tzinfo=timezone.utc), 100.0),
        (datetime(2024, 1, 3, tzinfo=timezone.utc), 101.0),
        (datetime(2024, 1, 4, tzinfo=timezone.utc), 102.0),
        (datetime(2024, 1, 5, tzinfo=timezone.utc), 103.0),
        (datetime(2024, 1, 8, tzinfo=timezone.utc), 104.0),
        (datetime(2024, 1, 9, tzinfo=timezone.utc), 105.0),
    ]
    rated = datetime(2024, 1, 2, 15, 0, tzinfo=timezone.utc)
    day1 = forward_close(closes, rated, 1)
    assert day1 == (100.0, closes[0][0])
    day5 = forward_close(closes, rated, 5)
    assert day5 == (104.0, closes[4][0])
    assert forward_close(closes, rated, 20) is None


def test_forward_close_uses_calendar_day_not_intraday_ts():
    """Afternoon ratings still use that day's midnight-stamped daily bar."""
    closes = [
        (datetime(2024, 1, 2, tzinfo=timezone.utc), 90.0),
        (datetime(2024, 1, 3, tzinfo=timezone.utc), 100.0),
        (datetime(2024, 1, 4, tzinfo=timezone.utc), 101.0),
    ]
    rated = datetime(2024, 1, 3, 20, 0, tzinfo=timezone.utc)
    assert forward_close(closes, rated, 1) == (100.0, closes[1][0])
    assert forward_close(closes, rated, 2) == (101.0, closes[2][0])


def test_outcome_status():
    assert outcome_status(entry_price=None, ready_5d=False, ready_20d=False) == "skipped"
    assert outcome_status(entry_price=10.0, ready_5d=False, ready_20d=False) == "pending"
    assert outcome_status(entry_price=10.0, ready_5d=True, ready_20d=False) == "partial"
    assert outcome_status(entry_price=10.0, ready_5d=True, ready_20d=True) == "complete"


def test_score_band_key():
    assert score_band_key(55) == "score_band=40_70"
    assert score_band_key(0) == "score_band=-15_15"
    assert score_band_key(None) is None
