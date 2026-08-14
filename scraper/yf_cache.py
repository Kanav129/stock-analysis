"""Per-run yfinance Ticker cache so gather nodes share one client."""
from __future__ import annotations

import threading
from typing import Any

import yfinance as yf

_local = threading.local()


def get_yf_ticker(symbol: str) -> Any:
    key = str(symbol or "").upper()
    cache: dict[str, Any] = getattr(_local, "tickers", None)
    if cache is None:
        cache = {}
        _local.tickers = cache
    ticker = cache.get(key)
    if ticker is None:
        ticker = yf.Ticker(key)
        cache[key] = ticker
    return ticker


def clear_yf_ticker_cache() -> None:
    _local.tickers = {}
