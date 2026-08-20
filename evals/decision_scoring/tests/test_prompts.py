from evals.decision_scoring.prompts import (
    DEFAULT_EVAL_VARIANTS,
    VARIANTS,
    SCORE_FIRST_SYSTEM,
    TIGHT_V1_SYSTEM,
)


def test_default_eval_is_score_first_pair():
    assert DEFAULT_EVAL_VARIANTS == ["score_first", "rubric_v1"]
    assert set(VARIANTS) >= {
        "baseline", "tight_v1", "tight_v1_hot",
        "tight_v1_think", "tight_v1_hot_think",
        "score_first", "score_first_think", "rubric_v1",
    }


def test_tight_defaults_to_hold_language():
    assert "default to HOLD" in TIGHT_V1_SYSTEM or "Default to HOLD" in TIGHT_V1_SYSTEM
    assert "not overly conservative" not in TIGHT_V1_SYSTEM
    assert "+28" not in TIGHT_V1_SYSTEM
    assert "+55" not in TIGHT_V1_SYSTEM


def test_tight_includes_short_medium_horizon():
    assert "short-to-medium" in TIGHT_V1_SYSTEM
    assert "this week" in TIGHT_V1_SYSTEM
    assert "few months" in TIGHT_V1_SYSTEM
    assert "only add on dips" in TIGHT_V1_SYSTEM


def test_score_first_prompt_keeps_cutover_legend():
    assert "pick the number first" in SCORE_FIRST_SYSTEM.lower()
    assert "+40 to +69" in SCORE_FIRST_SYSTEM
    assert "do not copy a neighbor" in SCORE_FIRST_SYSTEM.lower()
    assert "+28" in SCORE_FIRST_SYSTEM
    assert "±8" in SCORE_FIRST_SYSTEM or "+8" in SCORE_FIRST_SYSTEM


def test_rubric_prompt_reasons_then_scores():
    from evals.decision_scoring.prompts import RUBRIC_V1_SYSTEM

    assert "score_1_to_5" in RUBRIC_V1_SYSTEM
    assert "this_week_action" in RUBRIC_V1_SYSTEM
    assert "strong_buy" in RUBRIC_V1_SYSTEM
    assert "strong_sell" in RUBRIC_V1_SYSTEM
    assert "before" in RUBRIC_V1_SYSTEM.lower()
    assert "Do NOT pick an overall integer score" in RUBRIC_V1_SYSTEM
