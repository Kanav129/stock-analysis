"""Market / technicals node — synced stock_data with yfinance fallback."""
from __future__ import annotations

from typing import Any, Dict

from config.report_config import format_market_markdown
from rag_graphs.research_graph.state import ResearchState
from services.market_data_service import get_market_data
from utils.logger import logger


def gather_prices(state: ResearchState) -> Dict[str, Any]:
    ticker = state["ticker"]
    logger.info(f"---GATHER PRICES {ticker}---")

    market_data, live_price, error = get_market_data(ticker)
    if error or market_data is None or live_price is None:
        return {"errors": state.get("errors", []) + [error or f"No price data for {ticker}"]}

    sections = dict(state.get("sections_markdown") or {})
    sections["market"] = format_market_markdown(market_data)
    return {
        "market_data": market_data,
        "live_price": live_price,
        "sections_markdown": sections,
    }
