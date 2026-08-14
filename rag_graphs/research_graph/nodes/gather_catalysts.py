"""Earnings calendar, street consensus, and peer list — no LLM."""
from __future__ import annotations

from typing import Any, Dict

from rag_graphs.research_graph.state import ResearchState
from scraper.finnhub_scraper import FinnhubClient
from scraper.yf_cache import get_yf_ticker
from utils.logger import logger


def _fmt_earnings(calendar: Any) -> str:
    if calendar is None:
        return "Not available"
    try:
        import pandas as pd
    except ImportError:
        pd = None  # type: ignore
    if pd is not None and isinstance(calendar, pd.DataFrame) and not calendar.empty:
        row = calendar.iloc[0]
        bits = [f"{idx}: {row[idx]}" for idx in calendar.columns[:6]]
        return "; ".join(str(b) for b in bits)
    if isinstance(calendar, dict):
        date = calendar.get("Earnings Date") or calendar.get("earningsDate")
        return str(date or calendar)
    return str(calendar)


def _fmt_recs(trends: list[dict[str, Any]]) -> str:
    if not trends:
        return "No recommendation trends."
    latest = trends[0]
    return (
        f"As of {latest.get('period', 'n/a')}: "
        f"strongBuy {latest.get('strongBuy', 0)}, "
        f"buy {latest.get('buy', 0)}, "
        f"hold {latest.get('hold', 0)}, "
        f"sell {latest.get('sell', 0)}, "
        f"strongSell {latest.get('strongSell', 0)}"
    )


def _fmt_target(pt: dict[str, Any], live: float) -> str:
    if not pt:
        return "No consensus target."
    mean = pt.get("targetMean") or pt.get("targetMeanPrice") or pt.get("mean")
    high = pt.get("targetHigh") or pt.get("targetHighPrice") or pt.get("high")
    low = pt.get("targetLow") or pt.get("targetLowPrice") or pt.get("low")
    upside = ""
    try:
        if mean and live:
            upside = f" ({(float(mean) / live - 1) * 100:+.1f}% vs live)"
    except (TypeError, ValueError, ZeroDivisionError):
        upside = ""
    return f"Mean {mean}{upside}; high {high}; low {low}"


def format_catalysts_markdown(
    *,
    earnings: str,
    recs: str,
    target: str,
    peers: list[str],
) -> str:
    peer_line = ", ".join(peers[:8]) if peers else "None listed"
    return (
        "## Earnings / Street\n\n"
        f"- **Next / last earnings**: {earnings}\n"
        f"- **Street recommendations**: {recs}\n"
        f"- **Consensus target**: {target}\n"
        f"- **Peers**: {peer_line}\n"
    )


def gather_catalysts(state: ResearchState) -> Dict[str, Any]:
    ticker = state["ticker"]
    logger.info(f"---GATHER CATALYSTS {ticker}---")
    live = float(state.get("live_price") or 0)
    earnings = "Not available"
    recs_md = "No recommendation trends."
    target_md = "No consensus target."
    peers: list[str] = []

    try:
        stock = get_yf_ticker(ticker)
        calendar = getattr(stock, "calendar", None)
        earnings = _fmt_earnings(calendar)
    except Exception as exc:
        logger.warning(f"Earnings calendar failed for {ticker}: {exc}")
        earnings = f"Unavailable ({exc})"

    try:
        fh = FinnhubClient()
        recs_md = _fmt_recs(fh.get_recommendation_trends(ticker))
        target_md = _fmt_target(fh.get_price_target(ticker), live)
        raw_peers = fh.get_peers(ticker)
        peers = [p for p in raw_peers if isinstance(p, str) and p.upper() != ticker.upper()]
    except Exception as exc:
        logger.warning(f"Street/peers failed for {ticker}: {exc}")

    markdown = format_catalysts_markdown(
        earnings=earnings,
        recs=recs_md,
        target=target_md,
        peers=peers,
    )
    return {
        "catalysts_data": {
            "earnings": earnings,
            "recommendations": recs_md,
            "target": target_md,
            "peers": peers,
        },
        "sections_markdown": {"catalysts": markdown},
    }
