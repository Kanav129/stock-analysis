"""Decision synthesis — structured LLM call producing rating tag + AI score (−100…+100)."""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Dict

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from config.llm_config import (
    _chat_llm,
    _fallback_chain,
    _record_usage,
    resolve_analysis_model,
)
from config.rating_config import (
    RATING_TAGS,
    clamp_score,
    normalize_rating,
    reconcile_horizon_decision,
)
from config.report_config import (
    compute_dimension_alignment,
    compute_factor_scores,
    fundamentals_from_inputs,
)
from rag_graphs.research_graph.state import ResearchState
from services.portfolio_context_service import portfolio_markdown_for
from utils.logger import logger

# Tight HOLD-default prompt; thinking off (faster, fewer tokens; FC structured output).
DECISION_TEMPERATURE = 0.25
DECISION_ENABLE_THINKING = False
_PRIMARY_ATTEMPTS = 2


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
a mild bearish lean.

Typical bands (use the full range — do not cluster near 0):
- STRONG_SELL: -100 to -70
- SELL: -70 to -40
- REDUCE: -40 to -15
- HOLD: -15 to +15
- ACCUMULATE: +15 to +40
- BUY: +40 to +70
- STRONG_BUY: +70 to +100

Default to HOLD when evidence is mixed or inconclusive. Use REDUCE/ACCUMULATE when there
is a clear but moderate lean. Move to BUY/SELL or STRONG_* only when multiple factors
align with high conviction. Reserve STRONG_* for exceptional setups with aligned factors.

Keep rating and score consistent with the bands above. Be specific and actionable with
entry/stop/target when possible.

Horizon (mandatory): this is a short-to-medium decision. The user will only act on it
this week, then hold for a few months — not a day trade and not a multi-year "core
forever" call. The rating must answer: given the live price, should they transact
this week?
- BUY / STRONG_BUY means buy now, or within a few percent of the live price, this week,
  intending to hold for months.
- Do NOT rate BUY if the real advice is "hold the core / only add on dips" while the
  stock is extended or at highs. Waiting for a pullback is HOLD (or ACCUMULATE only if
  a dip this week is plausible and entry is that dip, not the live high).
- HOLD means do nothing this week at current prices.
- SELL / REDUCE means trim or exit this week.
entry must be hittable this week if the rating is BUY or SELL. stop and target should
assume a few-month hold, not a scalp.

You also receive the user's Personal Portfolio holdings table when available.
Stock research remains the primary driver of rating and score. Use the portfolio
for position_note and posture (size, add/trim/hold relative to existing weight).
You may slightly nudge rating and/or score when concentration or position size
has a clear, material effect (e.g. already a very large weight or sector cluster);
keep nudges modest and state them explicitly in reasoning. If portfolio influence
is none, say so briefly in reasoning.

When extra sections are present (Earnings / Street, Flows, Lockup, Kronos, Research
plan), they are first-class evidence — do not ignore them in favor of fundamentals
alone. Do not invent options flow, insider prints, or catalysts that are not in
the provided sections.

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
        text = text or ""
        return text[:max_chars] + ("..." if len(text) > max_chars else "")

    market_md = sections.get("market") or sections.get("technicals") or ""
    fundamentals_md = sections.get("fundamentals", "")
    news_md = sections.get("news", "")
    sentiment_md = sections.get("sentiment", "")
    catalysts_md = sections.get("catalysts", "")

    parts = [
        f"""## Market / Technicals
{truncate(market_md) or "*No technicals section — price/MA/RSI data was not written.*"}

## Fundamentals
{truncate(fundamentals_md)}

## News / Macro
{truncate(news_md)}

## Sentiment
{truncate(sentiment_md)}""",
    ]
    if catalysts_md.strip():
        parts.append(f"## Earnings / Street\n{truncate(catalysts_md, 2000)}")

    deep_blocks = (
        ("Flows / positioning", "flows", 2000),
        ("Lockup / supply", "lockup", 1500),
        ("Kronos forecast", "kronos", 1200),
        ("Policy", "policy", 1200),
        ("Research plan", "research_plan", 2500),
    )
    for title, key, limit in deep_blocks:
        body = (sections.get(key) or "").strip()
        if body:
            parts.append(f"## {title}\n{truncate(body, limit)}")

    factor_lines = "\n".join(
        f"- {label}: {factor_scores.get(key, 50)}"
        for key, label in (
            ("value", "Value"),
            ("growth", "Growth"),
            ("quality", "Quality"),
            ("momentum", "Momentum"),
            ("low_risk", "Low Risk"),
            ("sentiment", "Sentiment"),
        )
    )
    parts.append(
        f"""## Factor Scores (0-100; orthogonal to AI score)
{factor_lines}

## Live Price
${float(live_price):.2f}

{portfolio_markdown}
"""
    )
    base = "\n\n".join(parts)
    if priors_markdown:
        return base.rstrip() + "\n\n" + priors_markdown.strip() + "\n"
    return base


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, Mapping) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    raise TypeError("LLM response content must be text")


def _extract_json_object(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("LLM response did not contain a JSON object")


def _invoke_decision_on_llm(
    llm: Any,
    prompt: ChatPromptTemplate,
    inputs: dict[str, Any],
    *,
    enable_thinking: bool,
) -> Any:
    """Structured decision call.

    Qwen rejects tool_choice=required while enable_thinking=True, so thinking
    mode uses JSON parse directly. Non-thinking uses function_calling.
    """
    prompt_value = prompt.invoke(inputs)
    if enable_thinking:
        raw = llm.invoke(prompt_value)
        content = getattr(raw, "content", raw)
        payload = _extract_json_object(_message_text(content))
        decision = DecisionOutput.model_validate(payload)
        return {"raw": raw, "parsed": decision}

    structured_llm = llm.with_structured_output(
        DecisionOutput,
        method="function_calling",
        include_raw=True,
    )
    out = structured_llm.invoke(prompt_value)
    if isinstance(out, dict) and "parsed" in out:
        if out.get("parsed") is None:
            raise ValueError(
                f"structured output parsing failed: {out.get('parsing_error') or 'empty'}"
            )
    return out


def _call_decision_llm(
    prompt: ChatPromptTemplate,
    inputs: dict[str, Any],
) -> tuple[Any, str]:
    primary_name = resolve_analysis_model()
    last_exc: Exception | None = None

    for attempt in range(1, _PRIMARY_ATTEMPTS + 1):
        try:
            llm = _chat_llm(
                primary_name,
                DECISION_TEMPERATURE,
                enable_thinking=DECISION_ENABLE_THINKING,
            )
            result = _invoke_decision_on_llm(
                llm,
                prompt,
                inputs,
                enable_thinking=DECISION_ENABLE_THINKING,
            )
            _record_usage("analysis", primary_name, result)
            return result, primary_name
        except Exception as exc:
            last_exc = exc
            logger.warning(
                f"analysis LLM ({primary_name}) attempt "
                f"{attempt}/{_PRIMARY_ATTEMPTS} failed: {exc}"
            )

    for fallback_name in _fallback_chain("analysis", primary_name):
        try:
            # Cross-role / env fallbacks: prefer function_calling (thinking off).
            llm = _chat_llm(
                fallback_name,
                DECISION_TEMPERATURE,
                enable_thinking=False,
            )
            result = _invoke_decision_on_llm(
                llm,
                prompt,
                inputs,
                enable_thinking=False,
            )
            logger.info(f"analysis succeeded via fallback model {fallback_name}")
            _record_usage("analysis", fallback_name, result)
            return result, fallback_name
        except Exception as exc:
            last_exc = exc
            logger.warning(f"analysis fallback LLM ({fallback_name}) failed: {exc}")

    assert last_exc is not None
    raise last_exc


def synthesize_decision(state: ResearchState) -> Dict[str, Any]:
    ticker = state["ticker"]
    logger.info(f"---SYNTHESIZE DECISION {ticker}---")

    live_price = state.get("live_price") or 0.0
    report_type = (state.get("report_type") or "core").strip().lower()

    fundamental_data = dict(state.get("fundamental_data") or {})
    market_data = state.get("market_data") or {}
    sentiment_data = state.get("sentiment_data") or {}
    previous_scores = state.get("factor_scores") or {}
    if not fundamental_data.get("overview"):
        inputs = (previous_scores or {}).get("_inputs") if isinstance(previous_scores, dict) else None
        if inputs:
            fundamental_data = {**fundamentals_from_inputs(inputs), **fundamental_data}
    factor_scores = compute_factor_scores(
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
        ("human", """Synthesize the decision for {ticker} based on this analysis.

Horizon: act this week only; intended hold is a few months. Rating must match what
to do at/near the live price this week — not a "buy the dip later" thesis dressed as BUY.

{context}

Return your structured decision with rating tag + score (−100…+100)."""),
    ])

    used_model = "analysis"
    try:
        result, used_model = _call_decision_llm(
            prompt,
            {"ticker": ticker, "context": context},
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

    if isinstance(result, DecisionOutput):
        decision = result
    elif isinstance(result, Mapping):
        try:
            decision = DecisionOutput.model_validate(dict(result))
        except Exception as exc:
            return {
                "decision_ok": False,
                "error_message": f"Decision parse failed: {exc}"[:500],
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
    else:
        # Duck-typed objects (incl. test doubles) exposing DecisionOutput fields.
        decision = result

    rating = normalize_rating(decision.rating)
    score = clamp_score(decision.score)
    rating, score, entry = reconcile_horizon_decision(
        rating=rating,
        score=score,
        entry=decision.entry,
        live_price=float(live_price or 0),
        posture=decision.posture or "",
        position_note=decision.position_note or "",
    )

    entry_levels = {
        "entry": entry,
        "stop": decision.stop,
        "target": decision.target,
        "position_note": decision.position_note,
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
        "reasoning": decision.reasoning,
        "key_drivers": decision.key_drivers[:5],
        "supporting_headlines": [{"headline": h} for h in decision.supporting_headlines[:5]],
        "entry_levels": entry_levels,
        "factor_scores": factor_scores,
        "dimension_alignment": dimension_alignment,
        "calibration_note": calibration_note,
        "model": used_model,
        "posture": decision.posture,
    }
