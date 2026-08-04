"""Sentiment node — StockTwits aggregation + 1 LLM call for theme analysis."""
from __future__ import annotations

import json
from typing import Any, Dict

from langchain_core.prompts import ChatPromptTemplate

from config.llm_config import invoke_research_llm
from rag_graphs.research_graph.state import ResearchState
from scraper.social_scraper import SocialScraper
from utils.logger import logger

SENTIMENT_SYSTEM = """You are a social sentiment analyst for equities. Given StockTwits
sentiment data, write a structured analysis in markdown. Include:

1. **Overall Sentiment Direction** (Bullish / Bearish / Neutral) with confidence note.
2. **StockTwits Breakdown** — retail sentiment, themes, bullish/bearish ratios, sample messages.
3. **Key Narratives** — dominant narrative and any notable divergences in the sample.
4. **Catalysts and Risks** surfaced in social data.
5. A **Summary of Key Sentiment Signals** table.
6. **Bottom line** for traders.

Keep it under 800 words. Do not invent Reddit or other sources that are not in the data."""


def gather_sentiment(state: ResearchState) -> Dict[str, Any]:
    ticker = state["ticker"]
    logger.info(f"---GATHER SENTIMENT {ticker}---")

    try:
        scraper = SocialScraper()
        sentiment_summary = scraper.get_sentiment_summary(ticker)
    except Exception as exc:
        logger.warning(f"Social scraper failed for {ticker}: {exc}")
        sentiment_summary = {
            "stocktwits": {"total": 0, "bullish": 0, "bearish": 0, "error": str(exc)},
            "cross_source_alignment": "no_data",
        }

    st = sentiment_summary.get("stocktwits", {})

    if st.get("total", 0) == 0:
        markdown = f"*No social sentiment data found for {ticker} in the past week.*"
    else:
        try:
            prompt = ChatPromptTemplate.from_messages([
                ("system", SENTIMENT_SYSTEM),
                ("human", """Write the sentiment analysis for {ticker}. Here is the data:

## StockTwits
{stocktwits_json}

Output the analysis in markdown."""),
            ])
            result, _ = invoke_research_llm(
                prompt,
                {
                    "ticker": ticker,
                    "stocktwits_json": json.dumps({
                        "total_messages": st.get("total", 0),
                        "bullish": st.get("bullish", 0),
                        "bearish": st.get("bearish", 0),
                        "bullish_pct": st.get("bullish_pct", 0),
                        "bearish_pct": st.get("bearish_pct", 0),
                        "bull_bear_ratio": st.get("bull_bear_ratio"),
                        "strongly_bullish": st.get("is_strongly_bullish", False),
                        "sample": [{"body": m.get("body", ""), "sentiment": m.get("sentiment")}
                                   for m in st.get("sample", [])[:10]],
                    }, indent=2),
                },
                temperature=0.2,
            )
            markdown = result.content if hasattr(result, "content") else str(result)
        except Exception as exc:
            logger.error(f"Sentiment LLM failed: {exc}")
            markdown = f"*Sentiment analysis could not be generated: {exc}*"

    sections = state.get("sections_markdown", {})
    sections["sentiment"] = markdown

    return {"sentiment_data": sentiment_summary, "sections_markdown": sections}
