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

# After a successful core report, auto-enqueue deep dive when |score| >= this.
# BUY/SELL bands start at |40|; ACCUMULATE (~30) is not auto-deep.
AUTO_DEEP_SCORE_ABS_THRESHOLD = 40

# BUY/STRONG_BUY entry must be within this fraction of live price.
BUY_ENTRY_MAX_DISTANCE = 0.04
# If suggested entry is this far below live, the call is a dip, not a market buy.
DIP_ENTRY_MIN_DISCOUNT = 0.05

_DIP_PHRASES = (
    "on dips",
    "on a dip",
    "on dip",
    "pullback",
    "wait for",
    "don't chase",
    "do not chase",
    "avoid chasing",
    "on weakness",
    "accumulate on",
)


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


def rating_from_score(score: int) -> str:
    """Map a clamped AI score onto a rating tag (score is primary)."""
    value = clamp_score(score)
    if value >= 70:
        return "STRONG_BUY"
    if value >= 40:
        return "BUY"
    if value >= 16:
        return "ACCUMULATE"
    if value >= -15:
        return "HOLD"
    if value >= -39:
        return "REDUCE"
    if value >= -69:
        return "SELL"
    return "STRONG_SELL"


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


def _text_signals_wait_for_dip(*parts: str | None) -> bool:
    blob = " ".join(p or "" for p in parts).lower()
    return any(phrase in blob for phrase in _DIP_PHRASES)


def reconcile_horizon_decision(
    *,
    rating: str,
    score: int,
    entry: float | None,
    live_price: float,
    posture: str = "",
    position_note: str = "",
) -> tuple[str, int, float | None]:
    """Keep rating/score/entry consistent with a this-week horizon.

    Score is primary; rating is derived after any horizon cap. BUY/STRONG_BUY
    means transact near the live price this week. Waiting for a dip is HOLD or
    ACCUMULATE with entry below live.
    """
    score = clamp_score(score)
    tag = rating_from_score(score)
    # Incoming tag still flags a market-buy claim if the model scored below BUY
    # but labeled BUY (hint only). Treat either as a this-week buy.
    claimed_buy = tag in ("BUY", "STRONG_BUY") or normalize_rating(rating) in (
        "BUY",
        "STRONG_BUY",
    )
    live = float(live_price) if live_price else 0.0
    wait = _text_signals_wait_for_dip(posture, position_note)
    entry_val = None
    if entry is not None:
        try:
            entry_val = float(entry)
        except (TypeError, ValueError):
            entry_val = None

    if claimed_buy and live > 0:
        if entry_val is None:
            entry_val = live
        discount = (live - entry_val) / live
        premium = (entry_val - live) / live
        far_below = discount >= DIP_ENTRY_MIN_DISCOUNT
        far_above = premium > BUY_ENTRY_MAX_DISTANCE
        if wait or far_below:
            if wait and far_below and discount >= 0.08:
                score = min(int(score), 15)
            else:
                score = min(int(score), 38)
        elif far_above:
            entry_val = live
        tag = rating_from_score(score)

    if tag == "ACCUMULATE" and live > 0 and entry_val is None and wait:
        entry_val = round(live * (1 - DIP_ENTRY_MIN_DISCOUNT), 2)

    return tag, clamp_score(score), entry_val
