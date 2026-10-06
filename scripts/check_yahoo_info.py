#!/usr/bin/env python3
"""Live check that Yahoo quote info returns real fundamentals.

Usage:
    python scripts/check_yahoo_info.py NVDA

Exits 0 when at least one of forward/trailing P/E, beta, or gross margin is a
real number. Exits 1 on Invalid Crumb or an empty info payload.

After this change is deployed, re-check on the Render service with the same
command (or confirm a ticker log no longer says "no P/E, beta, or margin
fields"). Do not start a weekly analysis just to check.
"""
from __future__ import annotations

import sys


def main(argv: list[str]) -> int:
    import yfinance as yf
    from yfinance._http import HAS_CURL_CFFI

    symbol = (argv[1] if len(argv) > 1 else "NVDA").upper()
    print(f"yfinance={getattr(yf, '__version__', '?')} curl_cffi={HAS_CURL_CFFI} ticker={symbol}")
    if not HAS_CURL_CFFI:
        print("curl_cffi backend is not active")
        return 1
    try:
        info = yf.Ticker(symbol).info or {}
    except Exception as exc:
        print(f"info failed: {exc}")
        return 1
    if not isinstance(info, dict):
        print(f"info was {type(info).__name__}")
        return 1
    fields = {
        "trailingPE": info.get("trailingPE"),
        "forwardPE": info.get("forwardPE"),
        "beta": info.get("beta"),
        "grossMargins": info.get("grossMargins"),
        "revenueGrowth": info.get("revenueGrowth"),
    }
    print(fields)
    real = False
    for value in fields.values():
        if isinstance(value, (int, float)) and value == value:
            real = True
            break
    if not real:
        print("NO_REAL_INFO")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
