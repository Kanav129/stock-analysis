"""Shared rating tags and AI score scale (−100 strong sell … +100 strong buy)."""
from __future__ import annotations

# Ordered bearish → bullish
RATING_TAGS = (
    "STRONG_SELL",
    "SELL",
    "REDUCE",
    "HOLD",
    "ACCUMULATE",
    "BUY",
    "STRONG_BUY",
)

# Typical score bands (guidance for the model; not hard clamps per tag)
RATING_SCORE_BANDS = {
    "STRONG_SELL": (-100, -70),
    "SELL": (-70, -40),
    "REDUCE": (-40, -15),
    "HOLD": (-15, 15),
    "ACCUMULATE": (15, 40),
    "BUY": (40, 70),
    "STRONG_BUY": (70, 100),
}

RATING_SET = set(RATING_TAGS)


def normalize_rating(rating: str | None) -> str:
    if not rating:
        return "HOLD"
    key = str(rating).upper().replace(" ", "_").replace("-", "_")
    aliases = {
        "STRONGBUY": "STRONG_BUY",
        "STRONGSELL": "STRONG_SELL",
        "UNDERWEIGHT": "REDUCE",
        "OVERWEIGHT": "ACCUMULATE",
        "NEUTRAL": "HOLD",
    }
    key = aliases.get(key, key)
    return key if key in RATING_SET else "HOLD"


def clamp_score(score: int | float | None, default: int = 0) -> int:
    if score is None:
        return default
    try:
        return max(-100, min(100, int(round(float(score)))))
    except (TypeError, ValueError):
        return default


def score_from_legacy_confidence(rating: str, confidence: int | None) -> int:
    """Best-effort map old 0–100 confidence + 3-way rating into signed score."""
    conf = 50 if confidence is None else max(0, min(100, int(confidence)))
    r = normalize_rating(rating)
    # Map conviction away from neutral; weak confidence → closer to 0
    intensity = (conf / 100.0) * 80  # up to ±80 from legacy data
    if r in ("STRONG_BUY", "BUY", "ACCUMULATE"):
        sign = 1
        if r == "STRONG_BUY":
            intensity = max(intensity, 70)
        elif r == "BUY":
            intensity = max(intensity, 40)
        else:
            intensity = max(intensity, 20)
    elif r in ("STRONG_SELL", "SELL", "REDUCE"):
        sign = -1
        if r == "STRONG_SELL":
            intensity = max(intensity, 70)
        elif r == "SELL":
            intensity = max(intensity, 40)
        else:
            intensity = max(intensity, 20)
    else:
        return clamp_score((conf - 50) * 0.6)  # HOLD lean
    return clamp_score(sign * intensity)
