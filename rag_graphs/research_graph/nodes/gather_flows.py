"""Hot money / flows node — insider transactions + volume regime analysis + 1 LLM call."""
from __future__ import annotations

import json
from typing import Any, Dict

from langchain_core.prompts import ChatPromptTemplate

from config.llm_config import get_research_llm
from rag_graphs.research_graph.state import ResearchState
from scraper.finnhub_scraper import FinnhubClient
from utils.logger import logger

FLOWS_SYSTEM = """You are a flow/positioning analyst (a "hot money" desk analyst). Given insider transactions,
volume regime data, and institutional activity for a stock, write a structured analysis in markdown. Include:

1. **Volume Regimes & Abnormal Turnover** — table of notable volume events with assessment.
2. **Insider Transaction Cadence** — table of key insiders, recent sales, and assessment (10b5-1 vs discretionary).
3. **Flow & Institutional Activity** — hedge fund positioning, recent flow catalysts, macro liquidity context.
4. **Price Action & Positioning Summary** — key support/resistance levels, recovery patterns.
5. **Flow & Positioning Signal Table** — each signal with direction, strength, confidence, notes.
6. **Key Gaps / Unknowns** bullet points.
7. **Bottom-line flow assessment** paragraph.

Keep it under 1000 words. Be specific — reference dollar amounts and dates."""


def gather_flows(state: ResearchState) -> Dict[str, Any]:
    ticker = state["ticker"]
    logger.info(f"---GATHER FLOWS {ticker}---")

    try:
        fh = FinnhubClient()
        insider = fh.get_insider_summary(ticker)
        recommendations = fh.get_recommendation_trends(ticker)
        price_target = fh.get_price_target(ticker)
    except Exception as exc:
        logger.warning(f"Finnhub flows failed for {ticker}: {exc}")
        insider = {"transactions": [], "is_net_selling": False}
        recommendations = []
        price_target = {}

    market_data = state.get("market_data", {})
    volume_events = {
        "latest_volume": market_data.get("volume_latest", 0),
        "avg_volume_20d": market_data.get("volume_avg_20d", 0),
        "volume_ratio": market_data.get("volume_ratio", 1.0),
        "wide_range": market_data.get("wide_range_flag", False),
    }

    flows_data = {
        "insider": insider,
        "recommendations": recommendations[:12] if isinstance(recommendations, list) else [],
        "price_target": price_target,
        "volume_events": volume_events,
    }

    # ── LLM narrative ──
    try:
        llm = get_research_llm(temperature=0.2)
        prompt = ChatPromptTemplate.from_messages([
            ("system", FLOWS_SYSTEM),
            ("human", """Write the flows/positioning analysis for {ticker}. Data:

## Insider Transactions
{insider_json}

## Volume Events
{volume_json}

## Analyst Recommendations
{recs_json}

## Price Target
{pt_json}

Live price: ${live_price}

Output the analysis in markdown."""),
        ])
        chain = prompt | llm
        result = chain.invoke({
            "ticker": ticker,
            "insider_json": json.dumps(insider, indent=2),
            "volume_json": json.dumps(volume_events, indent=2),
            "recs_json": json.dumps(recommendations, indent=2),
            "pt_json": json.dumps(price_target, indent=2),
            "live_price": f"{state.get('live_price', 0):.2f}",
        })
        markdown = result.content if hasattr(result, "content") else str(result)
    except Exception as exc:
        logger.error(f"Flows LLM failed: {exc}")
        markdown = f"*Flows analysis could not be generated: {exc}*"

    sections = state.get("sections_markdown", {})
    sections["flows"] = markdown

    return {"flows_data": flows_data, "sections_markdown": sections}