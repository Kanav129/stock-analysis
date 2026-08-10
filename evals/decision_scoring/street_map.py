from __future__ import annotations

from config.rating_config import normalize_rating

_STREET_TO_TAGS: dict[str, set[str]] = {
    "strong_buy": {"STRONG_BUY", "BUY"},
    "buy": {"BUY", "ACCUMULATE"},
    "hold": {"HOLD", "ACCUMULATE", "REDUCE"},
    "sell": {"SELL", "REDUCE"},
    "strong_sell": {"STRONG_SELL", "SELL"},
}


def acceptable_tags(recommendation_key: str) -> set[str]:
    key = (recommendation_key or "").strip().lower().replace(" ", "_")
    return set(_STREET_TO_TAGS.get(key, {"HOLD"}))


def tag_within_tolerance(model_rating: str, recommendation_key: str) -> bool:
    return normalize_rating(model_rating) in acceptable_tags(recommendation_key)


def target_within_tolerance(
    model_target: float | None,
    street_mean: float | None,
    *,
    pct: float = 0.15,
) -> bool | None:
    if model_target is None or street_mean is None or street_mean == 0:
        return None
    return abs(float(model_target) - float(street_mean)) / abs(float(street_mean)) <= pct


def upside_pct(price: float, target_mean: float) -> float:
    return (float(target_mean) - float(price)) / float(price) * 100.0
