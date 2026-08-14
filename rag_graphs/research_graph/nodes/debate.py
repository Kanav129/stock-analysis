"""Debate node — one LLM call covering bull, bear, and research plan."""
from __future__ import annotations

from typing import Any, Dict

from langchain_core.prompts import ChatPromptTemplate

from config.llm_config import invoke_research_llm
from rag_graphs.research_graph.state import ResearchState
from services.portfolio_context_service import portfolio_markdown_for
from utils.logger import logger


def assemble_debate_context(
    sections: dict[str, Any],
    portfolio_markdown: str,
) -> str:
    parts: list[str] = []
    section_ids = [
        "market", "fundamentals", "news", "sentiment", "catalysts",
        "flows", "policy", "lockup", "kronos",
    ]
    for sid in section_ids:
        md = sections.get(sid, "")
        if md:
            parts.append(f"## {sid.title()}\n{md[:2000]}")
    body = "\n\n".join(parts)
    return f"{body}\n\n{portfolio_markdown}".strip()


COMBINED_DEBATE_SYSTEM = """You are the head of research running a structured internal debate.
Given full research, write ONE markdown document with these headings exactly:

## Bull Case
Aggressive growth case for adding. Cite specific data. Under 300 words.

## Bear Case
Conservative risk case for reducing or exiting. Under 300 words.

## Research Plan
The balanced thesis and strategic actions over 1-3 months.
- Label: `**Recommendation**: BUY/HOLD/SELL`
- `**Rationale**: ` paragraph
- `**Strategic Actions**: ` bullet points

## Trader Proposal
Concrete execution from the trader's perspective.
- `**Action**: BUY/HOLD/SELL`
- `**Reasoning**: ` paragraph
- `**Position Sizing**: ` guidance that references existing holdings when present
- End with: `FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**`

## Portfolio Decision
- `## Final Trading Decision: **BUY/HOLD/SELL**`
- `**Rationale:** ` paragraph
- `**Desk action right now:** ` bolded call-to-action

Stock research is the primary driver. Use the Personal Portfolio for sizing
relative to existing weight. Do not invent options flow or catalysts that are
not in the research. Under 1400 words total."""


def debate(state: ResearchState) -> Dict[str, Any]:
    ticker = state["ticker"]
    logger.info(f"---DEBATE {ticker}---")

    sections = state.get("sections_markdown", {})
    try:
        portfolio_md = portfolio_markdown_for(ticker)
    except Exception as exc:
        logger.warning(f"Portfolio context failed for {ticker}: {exc}")
        portfolio_md = (
            "## Personal Portfolio\n- Portfolio context unavailable.\n"
            "- Use generic position sizing."
        )

    full_context = assemble_debate_context(sections, portfolio_md)

    factor_scores = state.get("factor_scores", {})
    scores_note = (
        f"Factor Scores: Value {factor_scores.get('value', 0)}, "
        f"Growth {factor_scores.get('growth', 0)}, "
        f"Quality {factor_scores.get('quality', 0)}, "
        f"Momentum {factor_scores.get('momentum', 0)}, "
        f"Low Risk {factor_scores.get('low_risk', 0)}, "
        f"Sentiment {factor_scores.get('sentiment', 0)}"
    )
    live_price = state.get("live_price", 0) or 0

    try:
        prompt = ChatPromptTemplate.from_messages([
            ("system", COMBINED_DEBATE_SYSTEM),
            ("human", """Write the debate pack for {ticker} (${live_price:.2f}).

{scores_note}

## Full Research:
{context}"""),
        ])
        result, _ = invoke_research_llm(
            prompt,
            {
                "ticker": ticker,
                "live_price": float(live_price),
                "scores_note": scores_note,
                "context": full_context,
            },
            temperature=0.2,
        )
        research_plan = result.content if hasattr(result, "content") else str(result)
    except Exception as exc:
        research_plan = f"*Research plan generation failed: {exc}*"

    debate_data: dict[str, Any] = {"research_plan": research_plan}

    sections = dict(state.get("sections_markdown") or {})
    sections["research_plan"] = research_plan
    sections["trader_plan"] = ""
    sections["portfolio_decision"] = ""

    return {"debate_data": debate_data, "sections_markdown": sections}
