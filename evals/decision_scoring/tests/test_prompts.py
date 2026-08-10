from evals.decision_scoring.prompts import VARIANTS, TIGHT_V1_SYSTEM


def test_five_variants():
    assert set(VARIANTS) == {
        "baseline", "tight_v1", "tight_v1_hot",
        "tight_v1_think", "tight_v1_hot_think",
    }


def test_tight_defaults_to_hold_language():
    assert "default to HOLD" in TIGHT_V1_SYSTEM or "Default to HOLD" in TIGHT_V1_SYSTEM
    assert "not overly conservative" not in TIGHT_V1_SYSTEM
    assert "+28" not in TIGHT_V1_SYSTEM
    assert "+55" not in TIGHT_V1_SYSTEM
