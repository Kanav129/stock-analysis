"""Build frozen decision-scoring inputs from current research sources."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yfinance as yf

from scraper.finnhub_scraper import FinnhubClient
from services.portfolio_context_service import portfolio_markdown_for
from services.report_service import ReportService


DEFAULT_TICKERS = ["AAPL", "DIS", "NVDA", "ICLN", "META"]
FIXTURES_DIR = Path(__file__).with_name("fixtures")
_FINNHUB_COUNTS = ("strongBuy", "buy", "hold", "sell", "strongSell")


def _ticker_symbol(ticker: str) -> str:
    symbol = ticker.strip().upper()
    if not symbol:
        raise ValueError("ticker must not be empty")
    return symbol


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def build_ticker_fixture(ticker: str) -> dict[str, Any]:
    """Freeze the latest core report and portfolio context for one ticker."""
    symbol = _ticker_symbol(ticker)
    report = ReportService().get_latest_report(symbol, "core")
    if not report:
        raise LookupError(f"No core report found for {symbol}")

    return {
        "ticker": symbol,
        "report_id": report.get("id"),
        "live_price": _optional_float(report.get("live_price")),
        "factor_scores": report.get("factor_scores") or {},
        "sections_markdown": report.get("sections") or {},
        "portfolio_markdown": portfolio_markdown_for(symbol),
    }


def _latest_finnhub_counts(
    client: FinnhubClient, ticker: str
) -> dict[str, int | None] | None:
    try:
        trends = client.get_recommendation_trends(ticker)
    except Exception:
        return None
    rows = [row for row in trends if isinstance(row, dict)]
    if not rows:
        return None
    latest = max(rows, key=lambda row: str(row.get("period") or ""))
    return {key: _optional_int(latest.get(key)) for key in _FINNHUB_COUNTS}


def build_street_gold(tickers: list[str]) -> dict[str, Any]:
    """Fetch current analyst consensus data for the requested tickers."""
    client = FinnhubClient()
    result: dict[str, Any] = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "tickers": {},
    }

    for raw_ticker in tickers:
        symbol = _ticker_symbol(raw_ticker)
        info = yf.Ticker(symbol).info or {}
        item: dict[str, Any] = {
            "recommendation_key": info.get("recommendationKey"),
            "recommendation_mean": _optional_float(info.get("recommendationMean")),
            "target_mean": _optional_float(info.get("targetMeanPrice")),
            "price": _optional_float(info.get("currentPrice")),
            "n_analysts": _optional_int(info.get("numberOfAnalystOpinions")),
        }
        finnhub_rec = _latest_finnhub_counts(client, symbol)
        if finnhub_rec is not None:
            item["finnhub_rec"] = finnhub_rec
        result["tickers"][symbol] = item

    return result


def write_fixtures(tickers: list[str], out_dir: Path) -> None:
    """Write one report fixture per ticker plus street consensus data."""
    symbols = [_ticker_symbol(ticker) for ticker in tickers]
    out_dir.mkdir(parents=True, exist_ok=True)

    for symbol in symbols:
        fixture = build_ticker_fixture(symbol)
        (out_dir / f"{symbol}.json").write_text(
            json.dumps(fixture, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    street_gold = build_street_gold(symbols)
    (out_dir / "street_gold.json").write_text(
        json.dumps(street_gold, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    write_fixtures(DEFAULT_TICKERS, FIXTURES_DIR)


if __name__ == "__main__":
    main()
