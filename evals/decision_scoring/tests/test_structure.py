from evals.decision_scoring.structure import validate_decision_payload


def test_valid_payload_passes():
    r = validate_decision_payload(
        {
            "rating": "HOLD", "score": 5, "reasoning": "mixed",
            "key_drivers": ["valuation"], "supporting_headlines": ["h"],
            "entry": 100.0, "stop": 90.0, "target": 110.0,
            "position_note": "Hold", "posture": "neutral",
        },
        schema="score_first",
    )
    assert r.parsed_ok and r.rating_ok and r.score_ok and not r.errors


def test_garbage_rating_fails_rating_ok():
    r = validate_decision_payload(
        {
            "rating": "GARBAGE", "score": 5, "reasoning": "mixed",
            "key_drivers": ["valuation"], "supporting_headlines": ["h"],
            "entry": 100.0, "stop": 90.0, "target": 110.0,
            "position_note": "Hold", "posture": "neutral",
        },
        schema="score_first",
    )
    assert not r.rating_ok


def test_bad_score_fails():
    r = validate_decision_payload(
        {
            "rating": "BUY", "score": 999, "reasoning": "x",
            "key_drivers": ["a"], "supporting_headlines": [],
            "entry": None, "stop": None, "target": None,
            "position_note": "", "posture": "",
        },
        schema="score_first",
    )
    assert not r.score_ok


def _dim(level: int) -> dict:
    return {"bearish": ["risk"], "bullish": ["ok"], "score_1_to_5": level}


def test_rubric_payload_computes_composite_score():
    r = validate_decision_payload(
        {
            "bearish_factors": ["rich multiple", "extended tape"],
            "bullish_factors": ["franchise", "cash flow"],
            "fundamental_health": _dim(4),
            "valuation": _dim(2),
            "technical_momentum": _dim(3),
            "sentiment_and_news": _dim(3),
            "this_week_setup": _dim(2),
            "this_week_action": "hold",
            "reasoning": "mixed mega-cap, wait.",
            "key_drivers": ["valuation"],
            "supporting_headlines": ["h"],
            "entry": None,
            "stop": None,
            "target": None,
            "position_note": "Hold",
            "posture": "wait",
        },
        schema="rubric",
    )
    assert r.parsed_ok and r.score_ok and r.rating_ok
    assert r.normalized is not None
    assert r.normalized["score"] == -10
    assert r.normalized["rating"] == "HOLD"
