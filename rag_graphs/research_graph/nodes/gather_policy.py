"""Policy node — regulatory/geopolitical risk scan + 1 LLM call."""
from __future__ import annotations

import json
from typing import Any, Dict

import yfinance as yf
from langchain_core.prompts import ChatPromptTemplate

from config.llm_config import invoke_research_llm
from rag_graphs.research_graph.state import ResearchState
from utils.logger import logger

POLICY_SYSTEM = """You are a policy/regulatory analyst covering equities. Given a company's sector,
news context, and macro backdrop, write a structured policy/regulatory risk-and-catalyst analysis in markdown.
Include:

1. **Key Findings** — 5-7 major regulatory, legislative, trade, sanctions, or geopolitical risks/catalysts.
2. **Risk/Catalyst Summary Table** — columns: Risk/Catalyst | Mechanism | Horizon | Confidence.
3. **Recommendation Context** — which structural forces dominate.

Focus on material impacts to the company's business model, valuation, or competitive position.
Keep under 800 words."""


def gather_policy(state: ResearchState) -> Dict[str, Any]:
    ticker = state["ticker"]
    logger.info(f"---GATHER POLICY {ticker}---")

    # Get sector / industry context
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        sector = info.get("sector", "Technology")
        industry = info.get("industry", "Software")
    except Exception:
        sector = "Unknown"
        industry = "Unknown"

    news_md = state.get("sections_markdown", {}).get("news", "")[:3000]
    fundamentals = state.get("fundamental_data", {})

    policy_data = {
        "sector": sector,
        "industry": industry,
        "market_cap": fundamentals.get("overview", {}).get("market_cap"),
    }

    # ── LLM narrative ──
    try:
        prompt = ChatPromptTemplate.from_messages([
            ("system", POLICY_SYSTEM),
            ("human", """Write the policy analysis for {ticker} ({sector} / {industry}, market cap {mcap}).

News context:
{news}

Output the analysis in markdown."""),
        ])
        result, _ = invoke_research_llm(
            prompt,
            {
                "ticker": ticker,
                "sector": sector,
                "industry": industry,
                "mcap": f"${policy_data.get('market_cap', 0):,.0f}" if policy_data.get("market_cap") else "N/A",
                "news": news_md,
            },
            temperature=0.2,
        )
        markdown = result.content if hasattr(result, "content") else str(result)
    except Exception as exc:
        logger.error(f"Policy LLM failed: {exc}")
        markdown = f"*Policy analysis could not be generated: {exc}*"

    sections = state.get("sections_markdown", {})
    sections["policy"] = markdown

    return {"policy_data": policy_data, "sections_markdown": sections}