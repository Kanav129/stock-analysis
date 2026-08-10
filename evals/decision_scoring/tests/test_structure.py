from evals.decision_scoring.structure import validate_decision_payload


def test_valid_payload_passes():
    r = validate_decision_payload({
        "rating": "HOLD", "score": 5, "reasoning": "mixed",
        "key_drivers": ["valuation"], "supporting_headlines": ["h"],
        "entry": 100.0, "stop": 90.0, "target": 110.0,
        "position_note": "Hold", "posture": "neutral",
    })
    assert r.parsed_ok and r.rating_ok and r.score_ok and not r.errors


def test_bad_score_fails():
    r = validate_decision_payload({
        "rating": "BUY", "score": 999, "reasoning": "x",
        "key_drivers": ["a"], "supporting_headlines": [],
        "entry": None, "stop": None, "target": None,
        "position_note": "", "posture": "",
    })
    assert not r.score_ok
