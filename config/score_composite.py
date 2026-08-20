"""Programmatic AI score from 1–5 dimension ratings + this-week action cap."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from config.rating_config import clamp_score, rating_from_score

LEVEL_TO_SCORE = {1: -100, 2: -50, 3: 0, 4: 50, 5: 100}

DIMENSION_WEIGHTS: dict[str, float] = {
    "fundamental_health": 0.25,
    "valuation": 0.25,
    "this_week_setup": 0.20,
    "technical_momentum": 0.15,
    "sentiment_and_news": 0.15,
}

DIMENSION_LABELS = {
    "fundamental_health": "fund",
    "valuation": "val",
    "this_week_setup": "setup",
    "technical_momentum": "mom",
    "sentiment_and_news": "sent",
}

WEEK_ACTIONS = frozenset(
    {
        "strong_sell",
        "sell",
        "reduce",
        "hold",
        "accumulate",
        "buy",
        "strong_buy",
    }
)

_ACTION_ALIASES = {
    "strongsell": "strong_sell",
    "strongbuy": "strong_buy",
}


def normalize_week_action(action: str | None) -> str:
    raw = str(action or "hold").strip().lower().replace(" ", "_").replace("-", "_")
    raw = _ACTION_ALIASES.get(raw, raw)
    return raw if raw in WEEK_ACTIONS else "hold"


def map_level(level: int | float | None, default: int = 3) -> int:
    try:
        value = int(level)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        value = default
    if value not in LEVEL_TO_SCORE:
        value = default
    return LEVEL_TO_SCORE[value]


def apply_action_cap(score: int, action: str | None) -> int:
    """Clip how bullish a composite may print. Never inflates a mild score.

    `hold` does not clip: the 1–5 mix is the desk score so names are not pinned
    to the HOLD band edges (±15).
    """
    tagged = normalize_week_action(action)
    value = clamp_score(score)
    if tagged == "strong_sell":
        return min(value, -70)
    if tagged == "sell":
        return min(value, -40)
    if tagged == "reduce":
        return min(value, -16)
    if tagged == "accumulate":
        return min(value, 39)
    if tagged == "buy":
        return min(value, 69)
    return value


def _level_from_dim(dim: Any, default: int = 3) -> int:
    if dim is None:
        return default
    raw = dim.get("score_1_to_5") if isinstance(dim, Mapping) else getattr(
        dim, "score_1_to_5", None
    )
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value in LEVEL_TO_SCORE else default


def levels_from_decision(decision: Any) -> dict[str, int]:
    getter = decision.get if isinstance(decision, Mapping) else None
    levels: dict[str, int] = {}
    for key in DIMENSION_WEIGHTS:
        dim = getter(key) if getter else getattr(decision, key, None)
        levels[key] = _level_from_dim(dim)
    return levels


def action_from_decision(decision: Any) -> str:
    raw = (
        decision.get("this_week_action")
        if isinstance(decision, Mapping)
        else getattr(decision, "this_week_action", None)
    )
    return normalize_week_action(raw)


def weighted_raw_score(levels: Mapping[str, int]) -> float:
    total = 0.0
    for key, weight in DIMENSION_WEIGHTS.items():
        total += weight * map_level(levels.get(key))
    return total


def composite_score(
    decision: Any,
) -> tuple[int, str]:
    """Return clamped desk score and a short construction note."""
    levels = levels_from_decision(decision)
    action = action_from_decision(decision)
    raw = weighted_raw_score(levels)
    uncapped = clamp_score(round(raw))
    score = apply_action_cap(uncapped, action)
    rating = rating_from_score(score)
    bits = [
        f"{DIMENSION_LABELS[key]} {levels[key]}"
        for key in DIMENSION_WEIGHTS
    ]
    note = (
        "Score construction: "
        + " · ".join(bits)
        + f" · {action} → {score:+d} {rating}"
    )
    return score, note
