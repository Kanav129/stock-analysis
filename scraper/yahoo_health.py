"""Decide whether Yahoo quote fundamentals are usable.

The daily Alpha Vantage drip spends the free tier only when a sample of
equities cannot read real fundamentals: Invalid Crumb, empty ``stock.info``,
or null P/E, beta, gross margin, and revenue growth. One healthy ticker in
the sample means Yahoo is up, and that run makes no Alpha Vantage calls.
"""
from __future__ import annotations

import math
from typing import Any, Callable

FUNDAMENTAL_FIELDS = (
    "trailingPE",
    "forwardPE",
    "beta",
    "grossMargins",
    "revenueGrowth",
)
SAMPLE_SIZE = 3
# Liquid names that should carry at least one of those fields when Yahoo is up.
PROBE_PREFERENCE = ("AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META")


def classify_yahoo_info(info: Any, error: BaseException | None = None) -> str:
    """Return ok, invalid_crumb, empty, null_fields, or error."""
    if error is not None:
        if "crumb" in str(error).lower():
            return "invalid_crumb"
        return "error"
    if not isinstance(info, dict) or not info:
        return "empty"
    if not _has_real_fundamental(info):
        return "null_fields"
    return "ok"


def yahoo_sample_is_failing(statuses: list[str]) -> bool:
    """True only when every probed ticker failed. An empty sample is not a failure."""
    if not statuses:
        return False
    return all(status != "ok" for status in statuses)


def equity_probe_sample(tickers: list[str], *, etfs: set[str]) -> list[str]:
    """Up to three equities, preferring liquid names that should have fundamentals."""
    equities: list[str] = []
    seen: set[str] = set()
    for ticker in tickers:
        if ticker in etfs or ticker in seen:
            continue
        seen.add(ticker)
        equities.append(ticker)
    equity_set = set(equities)
    preferred = [ticker for ticker in PROBE_PREFERENCE if ticker in equity_set]
    rest = [ticker for ticker in equities if ticker not in PROBE_PREFERENCE]
    return (preferred + rest)[:SAMPLE_SIZE]


def read_yahoo_fundamentals(load: Callable[[], Any]) -> str:
    """Classify one ticker. Exception text is not logged; it can echo request URLs."""
    try:
        info = load()
    except Exception as exc:
        return classify_yahoo_info(None, exc)
    return classify_yahoo_info(info)


def _has_real_fundamental(info: dict[str, Any]) -> bool:
    for key in FUNDAMENTAL_FIELDS:
        value = info.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if isinstance(value, float) and math.isnan(value):
            continue
        return True
    return False
