"""Per-run yfinance Ticker cache so gather nodes share one client."""
from __future__ import annotations

import threading
from typing import Any

import yfinance as yf

from utils.logger import logger

_local = threading.local()
_curl_checked = False


def _warn_if_curl_cffi_missing() -> None:
    """Render crumb fetches fail when yfinance falls back to plain requests."""
    global _curl_checked
    if _curl_checked:
        return
    _curl_checked = True
    has_curl = False
    try:
        from yfinance._http import HAS_CURL_CFFI

        has_curl = bool(HAS_CURL_CFFI)
    except Exception:
        has_curl = False
    if not has_curl:
        logger.warning(
            "yfinance is not using curl_cffi; Yahoo crumb requests can return "
            "Invalid Crumb. Install curl_cffi>=0.15."
        )


def get_yf_ticker(symbol: str) -> Any:
    _warn_if_curl_cffi_missing()
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
