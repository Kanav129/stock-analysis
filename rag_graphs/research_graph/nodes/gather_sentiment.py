"""Sentiment node — social media aggregation + 1 LLM call for theme analysis."""
from __future__ import annotations

import json
from typing import Any, Dict

from langchain_core.prompts import ChatPromptTemplate

from config.llm_config import get_research_llm
from rag_graphs.research_graph.state import ResearchState
from scraper.social_scraper import SocialScraper
from utils.logger import logger

SENTIMENT_SYSTEM = """You are a social sentiment analyst for equities. Given sentiment data from
StockTwits and Reddit, write a structured analysis in markdown. Include:

1. **Overall Sentiment Direction** (Bullish / Bearish / Neutral) with confidence note.
2. **Source-by-Source Breakdown** — StockTwits (retail sentiment, themes, bullish/bearish ratios), Reddit (engagement level, key discussions).
3. **Divergences / Alignments / Key Narratives** — are sources in agreement? What's the dominant narrative?
4. **Catalysts and Risks** surfaced in social data.
5. A **Summary of Key Sentiment Signals** table.
6. **Bottom line** for traders.

Keep it under 800 words."""


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
            "reddit": {"total_posts": 0, "error": str(exc)},
            "cross_source_alignment": "no_data",
        }

    # ── LLM narrative ──
    st = sentiment_summary.get("stocktwits", {})
    reddit = sentiment_summary.get("reddit", {})

    if st.get("total", 0) == 0 and reddit.get("total_posts", 0) == 0:
        markdown = f"*No social sentiment data found for {ticker} in the past week.*"
    else:
        try:
            llm = get_research_llm(temperature=0.2)
            prompt = ChatPromptTemplate.from_messages([
                ("system", SENTIMENT_SYSTEM),
                ("human", """Write the sentiment analysis for {ticker}. Here is the data:

## StockTwits
{stocktwits_json}

## Reddit
{reddit_json}

Output the analysis in markdown."""),
            ])
            chain = prompt | llm
            result = chain.invoke({
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
                "reddit_json": json.dumps({
                    "total_posts": reddit.get("total_posts", 0),
                    "average_score": reddit.get("average_score", 0),
                    "average_comments": reddit.get("average_comments", 0),
                    "has_engagement": reddit.get("has_engagement", False),
                    "sample": [{"title": p.get("title", ""), "subreddit": p.get("subreddit", ""),
                                "score": p.get("score", 0), "num_comments": p.get("num_comments", 0)}
                               for p in reddit.get("sample", [])[:10]],
                }, indent=2),
            })
            markdown = result.content if hasattr(result, "content") else str(result)
        except Exception as exc:
            logger.error(f"Sentiment LLM failed: {exc}")
            markdown = f"*Sentiment analysis could not be generated: {exc}*"

    sections = state.get("sections_markdown", {})
    sections["sentiment"] = markdown

    return {"sentiment_data": sentiment_summary, "sections_markdown": sections}