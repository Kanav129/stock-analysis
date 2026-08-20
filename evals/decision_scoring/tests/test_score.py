from evals.decision_scoring.invoke_decision import InvokeResult
from evals.decision_scoring.score import aggregate_variant, score_call
from evals.decision_scoring.structure import StructureResult


def _invoke(*, call_ok=True, normalized=None):
    structure = StructureResult(
        parsed_ok=True,
        rating_ok=True,
        score_ok=True,
        reasoning_ok=True,
        drivers_ok=True,
        levels_types_ok=True,
        normalized=normalized
        or {
            "rating": "BUY",
            "score": 55,
            "target": 120.0,
        },
    )
    return InvokeResult(
        call_ok=call_ok,
        schema_method="function_calling",
        structure=structure,
        raw_error=None,
        latency_ms=12.5,
        model="test-model",
    )


def test_score_call_requires_call_and_all_structure_checks():
    invoke = _invoke(call_ok=False)

    row = score_call(
        invoke,
        {"recommendation_key": "buy", "target_mean": 120.0},
    )

    assert row["structure_pass"] is False
    assert row["tag_hit"] is None
    assert row["target_hit"] is None
    assert row["rating"] == "BUY"
    assert row["score"] == 55


def test_score_call_derives_rating_from_score():
    row = score_call(
        _invoke(normalized={"rating": "HOLD", "score": 55, "target": 120.0}),
        {"recommendation_key": "buy", "target_mean": 120.0},
    )
    assert row["rating"] == "BUY"
    assert row["tag_hit"] is True


def test_score_call_skips_missing_gold_values():
    row = score_call(
        _invoke(),
        {"recommendation_key": None, "target_mean": None},
    )

    assert row["structure_pass"] is True
    assert row["tag_hit"] is None
    assert row["target_hit"] is None


def test_aggregate_structure_gate():
    rows = [
        {
            "structure_pass": True,
            "tag_hit": True,
            "target_hit": True,
            "rating": "HOLD",
            "score": 5,
        },
        {
            "structure_pass": True,
            "tag_hit": False,
            "target_hit": None,
            "rating": "BUY",
            "score": 40,
        },
        {
            "structure_pass": False,
            "tag_hit": False,
            "target_hit": False,
            "rating": "STRONG_BUY",
            "score": 90,
        },
    ]

    aggregate = aggregate_variant(rows)

    assert abs(aggregate["structure_pass_rate"] - 2 / 3) < 1e-9
    assert aggregate["tag_accuracy"] == 0.5
    assert aggregate["target_accuracy"] == 1.0
    assert aggregate["distinct_scores"] == 2
    assert aggregate["bullish_skew"] == 0.5


def test_aggregate_returns_none_for_ungradable_metrics():
    aggregate = aggregate_variant(
        [
            {
                "structure_pass": False,
                "tag_hit": None,
                "target_hit": None,
                "rating": None,
                "score": None,
            }
        ]
    )

    assert aggregate == {
        "structure_pass_rate": 0.0,
        "tag_accuracy": None,
        "target_accuracy": None,
        "distinct_scores": 0,
        "bullish_skew": None,
    }
