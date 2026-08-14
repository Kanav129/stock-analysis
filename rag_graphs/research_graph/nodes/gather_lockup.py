"""Lockup node — insider selling + dilution analysis + 1 LLM call."""
from __future__ import annotations

import json
from typing import Any, Dict

from langchain_core.prompts import ChatPromptTemplate

from config.llm_config import invoke_research_llm
from rag_graphs.research_graph.state import ResearchState
from scraper.finnhub_scraper import FinnhubClient
from scraper.yf_cache import get_yf_ticker
from utils.logger import logger

LOCKUP_SYSTEM = """You are a lockup/supply-overhang analyst. Given insider transactions, share count trends,
and company financials, write a structured analysis in markdown. Include:

1. **Confirmed Tool Facts** — share count/dilution trend table, insider transactions table (key insiders, recent activity, approximate proceeds), news scan.
2. **Inference & Interpretation** — on lockup schedules, selling pressure assessment, dilution from equity comp.
3. **Summary Table** — factors with direction (supply pressure vs support), evidence, uncertainty.
4. **Final Assessment** — confirmed points, unknowns, and a verdict on lockup/overhang risk.

Keep under 800 words."""


def gather_lockup(state: ResearchState) -> Dict[str, Any]:
    ticker = state["ticker"]
    logger.info(f"---GATHER LOCKUP {ticker}---")

    try:
        fh = FinnhubClient()
        insider = fh.get_insider_summary(ticker)
    except Exception as exc:
        logger.warning(f"Finnhub insider failed: {exc}")
        insider = {"transactions": [], "is_net_selling": False}

    # Shares outstanding from yfinance
    try:
        stock = get_yf_ticker(ticker)
        info = stock.info
        shares_out = info.get("sharesOutstanding", info.get("impliedSharesOutstanding"))
    except Exception:
        shares_out = None

    fundamentals = state.get("fundamental_data", {})
    overview = fundamentals.get("overview", {})

    lockup_data = {
        "insider": insider,
        "shares_outstanding": shares_out,
        "market_cap": overview.get("market_cap"),
        "debt_equity": None,  # computed from AV data if available
        "fcf_margin": fundamentals.get("fcf_margin_pct", 0),
        "gross_margin": fundamentals.get("gross_margin_pct", 0),
    }

    # ── LLM narrative ──
    try:
        prompt = ChatPromptTemplate.from_messages([
            ("system", LOCKUP_SYSTEM),
            ("human", """Write the lockup/overhang analysis for {ticker}. Data:

## Insider Summary
{insider_json}

## Company Metrics
- Shares Outstanding: {shares}
- Market Cap: {mcap}
- FCF Margin: {fcf}%
- Gross Margin: {gm}%

Output the analysis in markdown."""),
        ])
        result, _ = invoke_research_llm(
            prompt,
            {
                "ticker": ticker,
                "insider_json": json.dumps(insider, indent=2),
                "shares": f"{shares_out:,.0f}" if shares_out else "N/A",
                "mcap": f"${overview.get('market_cap', 0):,.0f}" if overview.get("market_cap") else "N/A",
                "fcf": str(lockup_data["fcf_margin"]),
                "gm": str(lockup_data["gross_margin"]),
            },
            temperature=0.2,
        )
        markdown = result.content if hasattr(result, "content") else str(result)
    except Exception as exc:
        logger.error(f"Lockup LLM failed: {exc}")
        markdown = f"*Lockup/overhang analysis could not be generated: {exc}*"

    sections = state.get("sections_markdown", {})
    sections["lockup"] = markdown

    return {"lockup_data": lockup_data, "sections_markdown": sections}