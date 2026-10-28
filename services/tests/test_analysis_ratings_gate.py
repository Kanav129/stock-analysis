from pathlib import Path

from scripts.analysis_ratings_gate import (
    analysis_success_is_usable,
    should_fail_idle_without_ratings,
)


def test_success_requires_ratings_ok_for_full_universe():
    assert analysis_success_is_usable(
        {"ratings_ok": True, "good_count": 33, "universe_count": 33}
    )
    assert not analysis_success_is_usable(
        {"ratings_ok": False, "good_count": 0, "universe_count": 33}
    )
    assert not analysis_success_is_usable(
        {"ratings_ok": True, "good_count": 0, "universe_count": 33}
    )
    assert not analysis_success_is_usable(
        {"already_completed_today": True, "good_count": 33, "universe_count": 33}
    )


def test_idle_zero_good_ratings_fails_instead_of_resume():
    daily = {"good_count": 0, "universe_count": 33, "status": "partial", "can_resume": True}
    assert should_fail_idle_without_ratings(daily, running=False) is True
    assert should_fail_idle_without_ratings(daily, running=True) is False
    assert (
        should_fail_idle_without_ratings(
            {"good_count": 10, "can_resume": True},
            running=False,
        )
        is False
    )


def test_weekly_workflow_uses_ratings_gate():
    text = Path(".github/workflows/weekly-analysis.yml").read_text()
    assert "scripts/analysis_ratings_gate.py" in text or "analysis_ratings_gate" in text
    assert "analysis_success_is_usable" in text
    assert "should_fail_idle_without_ratings" in text
