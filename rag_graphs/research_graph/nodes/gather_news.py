"""News / macro node — local data aggregation + 1 LLM call for themed summary."""
from __future__ import annotations

import json
from typing import Any, Dict

import yfinance as yf
from langchain_core.prompts import ChatPromptTemplate

from config.llm_config import get_research_llm
from rag_graphs.research_graph.state import ResearchState
from scraper.finnhub_scraper import FinnhubClient
from utils.logger import logger

NEWS_SYSTEM = """You are a news/macro analyst. Given a list of recent news articles for a stock,
write a structured analysis in markdown. Include:

1. **Company-Specific Developments** — major events, product launches, partnerships, earnings, analyst actions.
2. **Macro & Geopolitical Context** — relevant macro trends, sector movements, geopolitical factors.
3. A **Summary Table** with columns: Category | Key Development | Impact Assessment (use emoji indicators).
4. A **Bottom Line** paragraph.

Keep it under 1000 words. Be specific and cite sources where applicable."""


def gather_news(state: ResearchState) -> Dict[str, Any]:
    ticker = state["ticker"]
    logger.info(f"---GATHER NEWS {ticker}---")

    articles: list[dict[str, Any]] = []

    # ── yfinance news ──
    try:
        stock = yf.Ticker(ticker)
        raw_news = stock.news or []
        for item in raw_news:
            content = item.get("content", {})
            articles.append({
                "headline": content.get("title", "") or item.get("title", ""),
                "summary": content.get("summary", "") or item.get("description", ""),
                "source": content.get("provider", {}).get("displayName", "") or item.get("publisher", ""),
                "url": content.get("canonicalUrl", {}).get("url", "") or item.get("link", ""),
                "posted": content.get("pubDate", "") or item.get("providerPublishTime", ""),
                "source_type": "yfinance",
            })
    except Exception as exc:
        logger.warning(f"yfinance news failed for {ticker}: {exc}")

    # ── Finnhub news ──
    try:
        fh = FinnhubClient()
        fh_news = fh.get_news_summary(ticker, limit=10)
        for a in fh_news:
            articles.append({**a, "source_type": "finnhub"})
    except Exception as exc:
        logger.warning(f"Finnhub news failed for {ticker}: {exc}")

    # ── Deduplicate by headline ──
    seen = set()
    deduped: list[dict[str, Any]] = []
    for a in articles:
        h = a.get("headline", "")[:80].lower()
        if h and h not in seen:
            seen.add(h)
            deduped.append(a)
    deduped = deduped[:20]

    news_data: dict[str, Any] = {
        "articles": deduped,
        "total_sources": len({a.get("source") for a in deduped}),
        "count": len(deduped),
    }

    # ── LLM narrative ──
    if not deduped:
        markdown = f"*No recent news found for {ticker}.*"
    else:
        try:
            llm = get_research_llm(temperature=0.2)
            prompt = ChatPromptTemplate.from_messages([
                ("system", NEWS_SYSTEM),
                ("human", """Write the news/macro analysis for {ticker}. Here are the recent articles:

{articles_json}

Output the analysis in markdown."""),
            ])
            chain = prompt | llm
            simplified = [
                {"headline": a["headline"], "source": a.get("source", ""), "summary": a.get("summary", "")[:300]}
                for a in deduped
            ]
            result = chain.invoke({
                "ticker": ticker,
                "articles_json": json.dumps(simplified, indent=2),
            })
            markdown = result.content if hasattr(result, "content") else str(result)
        except Exception as exc:
            logger.error(f"News LLM failed: {exc}")
            markdown = f"*News analysis could not be generated: {exc}*"

    sections = state.get("sections_markdown", {})
    sections["news"] = markdown

    return {"news_data": news_data, "sections_markdown": sections}