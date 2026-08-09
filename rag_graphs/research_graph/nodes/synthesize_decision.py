"""Decision synthesis — structured LLM call producing rating tag + AI score (−100…+100)."""
from __future__ import annotations

from typing import Any, Dict

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from config.llm_config import call_with_retry_then_fallback
from config.rating_config import RATING_TAGS, clamp_score, normalize_rating
from config.report_config import compute_dimension_alignment, compute_factor_scores
from rag_graphs.research_graph.state import ResearchState
from services.portfolio_context_service import portfolio_markdown_for
from utils.logger import logger


class DecisionOutput(BaseModel):
    rating: str = Field(
        description=(
            "One of: STRONG_SELL, SELL, REDUCE, HOLD, ACCUMULATE, BUY, STRONG_BUY"
        )
    )
    score: int = Field(
        ge=-100,
        le=100,
        description="Overall AI score from -100 (strong sell) to +100 (strong buy)",
    )
    reasoning: str = Field(description="Full reasoning for the decision in markdown")
    key_drivers: list[str] = Field(description="Top 3-5 drivers of the rating")
    supporting_headlines: list[str] = Field(
        description="Relevant news headlines supporting the decision"
    )
    entry: float | None = Field(default=None, description="Suggested entry price level")
    stop: float | None = Field(default=None, description="Suggested stop-loss level")
    target: float | None = Field(default=None, description="Suggested target price")
    position_note: str = Field(
        default="Maintain current position.",
        description="Position sizing guidance",
    )
    posture: str = Field(
        default="",
        description="Brief posture statement for the decision brief",
    )


DECISION_SYSTEM = f"""You are a senior portfolio manager on a personal trading desk. You receive
multi-analyst research on a stock (market/technicals, fundamentals, news, sentiment).

Produce:
1) A rating tag from this set (exactly): {", ".join(RATING_TAGS)}
2) An overall AI score from -100 to +100:
   -100 = strongest sell conviction
   0 = true neutral / no edge
   +100 = strongest buy conviction

Score is NOT "confidence %". A HOLD at +12 means a mild bullish lean; a HOLD at -18 means
a mild bearish lean. A BUY at +55 is clearly stronger than ACCUMULATE at +28.

Typical bands (use the full range — do not cluster near 0):
- STRONG_SELL: -100 to -70
- SELL: -70 to -40
- REDUCE: -40 to -15
- HOLD: -15 to +15
- ACCUMULATE: +15 to +40
- BUY: +40 to +70
- STRONG_BUY: +70 to +100

Be progressive, not overly conservative. If the evidence is clearly constructive or
deteriorating, move decisively into BUY/SELL or STRONG_* — do not default everything to
HOLD with a tiny score. Use REDUCE/ACCUMULATE when the lean is real but not a full
buy/sell. Reserve STRONG_* for high-conviction setups with aligned factors.

Keep rating and score consistent with the bands above. Be specific and actionable with
entry/stop/target when possible.

You also receive the user's Personal Portfolio holdings table when available.
Stock research remains the primary driver of rating and score. Use the portfolio
for position_note and posture (size, add/trim/hold relative to existing weight).
You may slightly nudge rating and/or score when concentration or position size
has a clear, material effect (e.g. already a very large weight or sector cluster);
keep nudges modest and state them explicitly in reasoning. If portfolio influence
is none, say so briefly in reasoning.

When Historical performance priors are present (deep analysis), use them only to
calibrate conviction and score magnitude. Current research remains the primary
driver — do not copy prior ratings. If priors conflict with the present evidence,
prefer the evidence and note the conflict briefly in reasoning.

Output Format: JSON with fields rating, score, reasoning (markdown), key_drivers (list),
supporting_headlines (list), entry (number or null), stop (number or null), target
(number or null), position_note (string), posture (string)."""


def build_decision_context(
    *,
    ticker: str,
    live_price: float,
    factor_scores: dict[str, Any],
    sections: dict[str, Any],
    portfolio_markdown: str,
    priors_markdown: str = "",
) -> str:
    def truncate(text: str, max_chars: int = 3000) -> str:
        return text[:max_chars] + ("..." if len(text) > max_chars else "")

    market_md = sections.get("market") or sections.get("technicals") or ""
    fundamentals_md = sections.get("fundamentals", "")
    news_md = sections.get("news", "")
    sentiment_md = sections.get("sentiment", "")

    base = f"""## Market / Technicals
{truncate(market_md) or truncate(fundamentals_md, 1500)}

## Fundamentals
{truncate(fundamentals_md)}

## News / Macro
{truncate(news_md)}

## Sentiment
{truncate(sentiment_md)}

## Factor Scores (0-100; orthogonal to AI score)
- Value: {factor_scores.get('value', 50)}
- Growth: {factor_scores.get('growth', 50)}
- Quality: {factor_scores.get('quality', 50)}
- Momentum: {factor_scores.get('momentum', 50)}
- Low Risk: {factor_scores.get('low_risk', 50)}
- Sentiment: {factor_scores.get('sentiment', 50)}

## Live Price
${float(live_price):.2f}

{portfolio_markdown}
"""
    if priors_markdown:
        return base.rstrip() + "\n\n" + priors_markdown.strip() + "\n"
    return base


def synthesize_decision(state: ResearchState) -> Dict[str, Any]:
    ticker = state["ticker"]
    logger.info(f"---SYNTHESIZE DECISION {ticker}---")

    live_price = state.get("live_price") or 0.0
    report_type = (state.get("report_type") or "core").strip().lower()

    fundamental_data = state.get("fundamental_data") or {}
    market_data = state.get("market_data") or {}
    sentiment_data = state.get("sentiment_data") or {}

    factor_scores = state.get("factor_scores") or compute_factor_scores(
        fundamental_data, market_data, sentiment_data
    )

    sections = state.get("sections_markdown") or {}

    try:
        portfolio_md = portfolio_markdown_for(ticker)
    except Exception as exc:
        logger.warning(f"Portfolio context failed for {ticker}: {exc}")
        portfolio_md = (
            "## Personal Portfolio\n- Portfolio context unavailable.\n"
            "- Use generic position sizing."
        )

    priors_md = ""
    if report_type == "deep":
        try:
            from services.analysis_knowledge_service import analysis_knowledge_service

            priors_md = analysis_knowledge_service.priors_for_deep(
                ticker,
                score=state.get("score"),
                factor_scores=factor_scores,
                key_drivers=list(state.get("key_drivers") or []),
            )
        except Exception as exc:
            logger.warning(f"Deep priors failed for {ticker}: {exc}")
            priors_md = (
                "## Historical performance priors\n"
                "- Priors unavailable (lookup failed). "
                "Score from current research only."
            )

    context = build_decision_context(
        ticker=ticker,
        live_price=float(live_price),
        factor_scores=factor_scores,
        sections=sections,
        portfolio_markdown=portfolio_md,
        priors_markdown=priors_md,
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", DECISION_SYSTEM),
        ("human", """Synthesize the decision for {ticker} based on this analysis:

{context}

Return your structured decision with rating tag + score (−100…+100)."""),
    ])

    def _invoke(llm):
        structured_llm = llm.with_structured_output(
            DecisionOutput,
            method="function_calling",
            include_raw=True,
        )
        out = (prompt | structured_llm).invoke({"ticker": ticker, "context": context})
        # include_raw → {"raw": AIMessage, "parsed": DecisionOutput}; keep both for usage tracking
        return out

    used_model = "analysis"
    try:
        result, used_model = call_with_retry_then_fallback(
            role="analysis",
            temperature=0.25,
            call=_invoke,
        )
    except Exception as exc:
        logger.error(f"Decision LLM failed: {exc}")
        return {
            "decision_ok": False,
            "error_message": str(exc)[:500],
            "rating": None,
            "score": None,
            "reasoning": f"Decision generation failed: {exc}",
            "key_drivers": [],
            "supporting_headlines": [],
            "entry_levels": {
                "entry": None,
                "stop": None,
                "target": None,
                "position_note": "Unable to determine — review manually.",
            },
            "factor_scores": factor_scores,
            "dimension_alignment": {},
            "calibration_note": "Analysis failed",
            "model": used_model,
            "posture": "",
        }

    if isinstance(result, dict) and "parsed" in result:
        result = result["parsed"]
    if result is None:
        return {
            "decision_ok": False,
            "error_message": "Structured decision parse returned empty",
            "rating": None,
            "score": None,
            "reasoning": "Decision generation failed: empty structured output",
            "key_drivers": [],
            "supporting_headlines": [],
            "entry_levels": {
                "entry": None,
                "stop": None,
                "target": None,
                "position_note": "Unable to determine — review manually.",
            },
            "factor_scores": factor_scores,
            "dimension_alignment": {},
            "calibration_note": "Analysis failed",
            "model": used_model,
            "posture": "",
        }

    rating = normalize_rating(result.rating)
    score = clamp_score(result.score)

    entry_levels = {
        "entry": result.entry,
        "stop": result.stop,
        "target": result.target,
        "position_note": result.position_note,
    }

    dimension_alignment = compute_dimension_alignment(factor_scores, rating)

    data_flags: list[str] = []
    av_errors = fundamental_data.get("av_errors") or {}
    if av_errors:
        data_flags.append(f"fundamental gaps ({', '.join(av_errors.keys())})")
    if (sentiment_data.get("stocktwits") or {}).get("total", 0) == 0 and sentiment_data:
        data_flags.append("thin sentiment feed")
    if fundamental_data and fundamental_data.get("overview", {}).get("forward_pe") is None:
        data_flags.append("missing forward P/E")
    calibration_note = (
        f"AI score {score:+d} · {rating}"
        + (f" · gaps: {', '.join(data_flags)}" if data_flags else "")
    )

    return {
        "decision_ok": True,
        "error_message": None,
        "rating": rating,
        "score": score,
        "reasoning": result.reasoning,
        "key_drivers": result.key_drivers[:5],
        "supporting_headlines": [{"headline": h} for h in result.supporting_headlines[:5]],
        "entry_levels": entry_levels,
        "factor_scores": factor_scores,
        "dimension_alignment": dimension_alignment,
        "calibration_note": calibration_note,
        "model": used_model,
        "posture": result.posture,
    }
