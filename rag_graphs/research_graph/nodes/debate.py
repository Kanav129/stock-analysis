"""Multi-analyst debate node — 4 LLM calls (bull, bear, neutral, research manager)."""
from __future__ import annotations

from typing import Any, Dict

from langchain_core.prompts import ChatPromptTemplate

from config.llm_config import invoke_research_llm
from rag_graphs.research_graph.state import ResearchState
from services.portfolio_context_service import portfolio_markdown_for
from utils.logger import logger

BULL_SYSTEM = """You are an aggressive growth analyst with a bullish tilt. Given full research on a stock,
write your bull case. Argue for adding to the position. Cite specific data points. Be forceful but grounded.
Output in markdown, under 400 words."""

BEAR_SYSTEM = """You are a conservative risk manager with a bearish tilt. Given full research on a stock,
write your bear case. Argue for reducing or exiting. Think about what could go wrong. Be skeptical.
Output in markdown, under 400 words."""

NEUTRAL_SYSTEM = """You are a balanced, probabilistic portfolio manager. Given full research on a stock,
the bull/bear cases, and the user's Personal Portfolio holdings when available, write a fair synthesis
that weighs both sides. Recommend a specific action size (add/trim/hold) with clear reasoning.

Stock research is the primary driver of your recommendation and action sizing. Use the portfolio
for position sizing relative to existing holdings and book weight. You may slightly nudge the
recommendation only when concentration or position size has a clear, material effect (e.g. already
a very large weight or sector cluster); keep nudges modest and state them explicitly in your reasoning.
If portfolio influence is none, say so briefly. Position sizing must reference existing holdings when present.

Output in markdown, under 400 words."""

RESEARCH_MANAGER_SYSTEM = """You are the head of research. You receive three analyst perspectives
(bull/aggressive, bear/conservative, neutral/balanced) plus the full research sections and the
user's Personal Portfolio holdings when available.

Stock research is the primary driver of rating, score, and final recommendation. Use the portfolio
for position sizing (size relative to book; add/trim/hold relative to existing weight). You may
slightly nudge the final call when concentration or position size has a clear, material effect
(e.g. already a very large weight or sector cluster); keep nudges modest and state them explicitly
in the Research Plan rationale, Trader Proposal reasoning, or Portfolio Decision rationale. If
portfolio influence is none, say so briefly.

Synthesize them into the final decision chain:

1. **Research Plan** — the balanced thesis and strategic actions. What to do over 1-3 months.
   - Label: `**Recommendation**: BUY/HOLD/SELL`
   - `**Rationale**: ` paragraph
   - `**Strategic Actions**: ` bullet points

2. **Trader Proposal** — concrete execution plan from the trader's perspective.
   - `**Action**: BUY/HOLD/SELL`
   - `**Reasoning**: ` paragraph
   - `**Position Sizing**: ` specific guidance that references existing holdings when present
     (size relative to book; concentration).
   - End with: `FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**`

3. **Portfolio Decision** — the final, authoritative call.
   - `## Final Trading Decision: **BUY/HOLD/SELL**`
   - `**Rationale:** ` paragraph
   - `**Standardized dimensions snapshot alignment:** ` paragraph
   - `**Desk action right now:** ` bolded call-to-action

Output in markdown. Under 1200 words total. Make the final call clear and decisive."""


def assemble_debate_context(
    sections: dict[str, Any],
    portfolio_markdown: str,
) -> str:
    parts: list[str] = []
    section_ids = [
        "market", "fundamentals", "news", "sentiment",
        "flows", "policy", "lockup", "kronos",
    ]
    for sid in section_ids:
        md = sections.get(sid, "")
        if md:
            parts.append(f"## {sid.title()}\n{md[:2000]}")
    body = "\n\n".join(parts)
    return f"{body}\n\n{portfolio_markdown}".strip()


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

    # Same assembled context (research + portfolio) for all four analysts.
    full_context = assemble_debate_context(sections, portfolio_md)

    factor_scores = state.get("factor_scores", {})
    scores_note = f"Factor Scores: Value {factor_scores.get('value', 0)}, Growth {factor_scores.get('growth', 0)}, "
    scores_note += f"Quality {factor_scores.get('quality', 0)}, Momentum {factor_scores.get('momentum', 0)}, "
    scores_note += f"Low Risk {factor_scores.get('low_risk', 0)}, Sentiment {factor_scores.get('sentiment', 0)}"

    live_price = state.get("live_price", 0)

    debate_data: dict[str, Any] = {}

    # ── Bull analyst ──
    try:
        prompt = ChatPromptTemplate.from_messages([
            ("system", BULL_SYSTEM),
            ("human", f"Research on {ticker} (${live_price:.2f}):\n{{context}}"),
        ])
        result, _ = invoke_research_llm(prompt, {"context": full_context}, temperature=0.3)
        bull_case = result.content if hasattr(result, "content") else str(result)
    except Exception as exc:
        bull_case = f"*Bull case generation failed: {exc}*"

    # ── Bear analyst ──
    try:
        prompt = ChatPromptTemplate.from_messages([
            ("system", BEAR_SYSTEM),
            ("human", f"Research on {ticker} (${live_price:.2f}):\n{{context}}"),
        ])
        result, _ = invoke_research_llm(prompt, {"context": full_context}, temperature=0.3)
        bear_case = result.content if hasattr(result, "content") else str(result)
    except Exception as exc:
        bear_case = f"*Bear case generation failed: {exc}*"

    # ── Neutral analyst (sees both) ──
    try:
        prompt = ChatPromptTemplate.from_messages([
            ("system", NEUTRAL_SYSTEM),
            ("human", f"""Research on {ticker} (${live_price:.2f}):

{scores_note}

## Bull Analyst Case:
{bull_case}

## Bear Analyst Case:
{bear_case}

## Full Research:
{{context}}

Synthesize a balanced recommendation."""),
        ])
        result, _ = invoke_research_llm(prompt, {"context": full_context}, temperature=0.2)
        neutral_case = result.content if hasattr(result, "content") else str(result)
    except Exception as exc:
        neutral_case = f"*Neutral synthesis failed: {exc}*"

    # ── Research manager (final synthesis) ──
    try:
        prompt = ChatPromptTemplate.from_messages([
            ("system", RESEARCH_MANAGER_SYSTEM),
            ("human", f"""Synthesize the final decision chain for {ticker} (${live_price:.2f}).

{scores_note}

## Bull (Aggressive):
{bull_case}

## Bear (Conservative):
{bear_case}

## Neutral (Balanced):
{neutral_case}

## Full Research:
{{context}}

Output the Research Plan, Trader Proposal, and Portfolio Decision."""),
        ])
        result, _ = invoke_research_llm(prompt, {"context": full_context}, temperature=0.15)
        research_plan = result.content if hasattr(result, "content") else str(result)
    except Exception as exc:
        research_plan = f"*Research plan generation failed: {exc}*"

    debate_data["bull_case"] = bull_case
    debate_data["bear_case"] = bear_case
    debate_data["neutral_case"] = neutral_case
    debate_data["research_plan"] = research_plan

    sections = state.get("sections_markdown", {})
    sections["research_plan"] = research_plan
    sections["trader_plan"] = ""  # embedded in research_plan
    sections["portfolio_decision"] = ""  # embedded in research_plan

    return {"debate_data": debate_data, "sections_markdown": sections}
