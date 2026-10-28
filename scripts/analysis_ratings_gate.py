"""Decide whether a weekly analysis poll is a real success.

GitHub Actions imports this after checkout. Keep the module dependency-free.
"""

from __future__ import annotations


def analysis_success_is_usable(daily: dict | None) -> bool:
    """True when the status payload says every universe ticker has a good decision."""
    if not isinstance(daily, dict):
        return False
    if daily.get("ratings_ok") is not True:
        return False
    try:
        good = int(daily.get("good_count") or 0)
        universe = int(daily.get("universe_count") or 0)
    except (TypeError, ValueError):
        return False
    return universe > 0 and good >= universe


def should_fail_idle_without_ratings(daily: dict | None, *, running: bool) -> bool:
    """Idle run with zero good decisions should fail the job instead of resume-looping.

    A partial run that already produced some decisions stays resumable. Missing
    ``good_count`` (older API) keeps the previous resume behavior.
    """
    if running or not isinstance(daily, dict) or "good_count" not in daily:
        return False
    try:
        good = int(daily.get("good_count") or 0)
    except (TypeError, ValueError):
        return False
    return good <= 0
