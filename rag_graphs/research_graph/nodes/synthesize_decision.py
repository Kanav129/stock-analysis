"""Decision synthesis — Max fills a 1–5 rubric; Python computes the desk score."""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Dict, Literal

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field, field_validator

from config.llm_config import (
    DEFAULT_THINKING_BUDGET,
    DEFAULT_THINKING_TIMEOUT_SECONDS,
    _chat_llm,
    _fallback_chain,
    _record_usage,
    resolve_analysis_model,
    resolve_decision_enable_thinking,
)
from config.rating_config import (
    clamp_score,
    rating_from_score,
    reconcile_horizon_decision,
)
from config.report_config import (
    compute_dimension_alignment,
    compute_factor_scores,
    fundamentals_from_inputs,
)
from config.score_composite import composite_score
from rag_graphs.research_graph.state import ResearchState
from services.portfolio_context_service import portfolio_markdown_for
from utils.logger import logger

# Rubric-composite prompt; thinking off unless Settings/env enable it.
DECISION_TEMPERATURE = 0.25
DECISION_ENABLE_THINKING = False
_PRIMARY_ATTEMPTS = 2
DESK_SCORES_LIMIT = 40
CONTEXT_TRUNCATE_CHARS = 5000

WeekAction = Literal[
    "strong_sell",
    "sell",
    "reduce",
    "hold",
    "accumulate",
    "buy",
    "strong_buy",
]


class DimensionRating(BaseModel):
    bearish: list[str] = Field(
        description="1–4 bearish points from the matching research section",
        min_length=1,
        max_length=4,
    )
    bullish: list[str] = Field(
        description="1–4 bullish points from the matching research section",
        min_length=1,
        max_length=4,
    )
    score_1_to_5: int = Field(
        ge=1,
        le=5,
        description="Fill only after bearish and bullish lists",
    )


class DecisionOutput(BaseModel):
    bearish_factors: list[str] = Field(
        description="Overall key risks (2–5)",
        min_length=2,
        max_length=5,
    )
    bullish_factors: list[str] = Field(
        description="Overall key catalysts (2–5)",
        min_length=2,
        max_length=5,
    )
    fundamental_health: DimensionRating = Field(
        description="Growth, margins, balance sheet from fundamentals research"
    )
    valuation: DimensionRating = Field(
        description="Multiples vs history/peers"
    )
    technical_momentum: DimensionRating = Field(
        description="Trend, MAs, RSI, extension from market/technicals"
    )
    sentiment_and_news: DimensionRating = Field(
        description="Revisions, headlines, social from news + sentiment"
    )
    this_week_setup: DimensionRating = Field(
        description="Is live a good place to transact this week?"
    )
    this_week_action: WeekAction = Field(
        description=(
            "What to do at/near live this week. Does not set the numeric score."
        )
    )
    reasoning: str = Field(description="Full reasoning for the decision in markdown")
    key_drivers: list[str] = Field(description="Top 3-5 drivers of the decision")
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

    @field_validator("this_week_action", mode="before")
    @classmethod
    def _normalize_action(cls, value: Any) -> str:
        raw = str(value or "hold").strip().lower().replace(" ", "_").replace("-", "_")
        aliases = {"strongsell": "strong_sell", "strongbuy": "strong_buy"}
        return aliases.get(raw, raw)


DECISION_SYSTEM = """You are a senior portfolio manager on a personal trading desk. You receive
multi-analyst research on a stock (market/technicals, fundamentals, news, sentiment).

Do NOT pick an overall integer score or a rating tag. The server computes the desk
score from your 1–5 dimension ratings and this_week_action.

Work in this order:
1. Book-level bearish_factors then bullish_factors (2–5 each) from the research.
2. For EACH dimension: fill bearish, then bullish, THEN score_1_to_5. Never pick
   the 1–5 first and justify it after. Use only evidence in the provided sections.
3. this_week_action: strong_sell | sell | reduce | hold | accumulate | buy | strong_buy.
   This is the this-week horizon (transact near live vs wait). It does not set the
   integer — the 1–5 mix does. Do not default every name to hold. Use accumulate when
   the real advice is add on a nearby dip; buy/strong_buy when transacting near live
   this week is warranted. Do not pick buy/strong_buy if the real advice is wait for
   a dip while the stock is extended.
4. reasoning, key_drivers, headlines, entry/stop/target, position_note, posture.

1–5 anchors (same for every dimension):
- 1 deteriorating / very expensive / breakdown / do not transact
- 2 weak / rich / fading / wait
- 3 mixed / fair / range / no edge this week
- 4 healthy / reasonable / constructive / add on a nearby dip
- 5 accelerating / cheap / breakout / buy near live this week

Dimensions:
- fundamental_health — fundamentals section (growth, margins, balance sheet)
- valuation — multiples vs history/peers (use the full 1–5; rich mega-caps are often 1–2)
- technical_momentum — market/technicals
- sentiment_and_news — news + sentiment
- this_week_setup — is live a good place to transact this week? Extended/high → 1–2;
  washout/attractive → 4–5

Horizon: act this week only; intended hold is a few months. entry must be hittable
this week if this_week_action is buy or strong_buy (or sell / strong_sell). stop and
target assume a few-month hold.

Portfolio is for position_note and posture. Stock research drives dimension 1–5s.
If a desk scores table is present, do not copy a neighbor's 1–5s or action.
Priors calibrate conviction only; current research dominates; do not copy the last
tag. If last +20d missed, say so in reasoning rather than blindly reversing.
Do not invent flows, insider prints, or catalysts missing from the sections.

Examples (structure only — no overall score):

Broken name: bearish_factors emphasize deteriorating FCF and a technical breakdown;
fundamental_health and this_week_setup 1s; valuation maybe 2 if already cheap;
this_week_action strong_sell or sell.

Mixed mega-cap: strong franchise (fund 4) but rich multiples (val 2) and extended
price (setup 2); this_week_action hold or accumulate. Do not mark buy just because
the business is high quality.

Strong setup: accelerating results, reasonable/cheap valuation, washout, constructive
tape; several 4–5s; this_week_action buy or strong_buy.

Output the structured object. Fill lists before every 1–5."""


def build_decision_context(
    *,
    ticker: str,
    live_price: float,
    factor_scores: dict[str, Any],
    sections: dict[str, Any],
    portfolio_markdown: str,
    priors_markdown: str = "",
    desk_scores_markdown: str = "",
) -> str:
    def truncate(text: str, max_chars: int = CONTEXT_TRUNCATE_CHARS) -> str:
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
    if desk_scores_markdown.strip():
        parts.append(desk_scores_markdown.strip())
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


def desk_scores_markdown_for(ticker: str) -> str:
    """Other holdings' latest scores so this name can be ranked relatively."""
    try:
        from services.ratings_service import RatingsService

        rows = RatingsService().get_latest_ratings()
    except Exception as exc:
        logger.warning(f"Desk scores lookup failed for {ticker}: {exc}")
        return ""
    lines: list[str] = []
    exclude = ticker.upper()
    for row in rows:
        other = str(row.get("ticker") or "").upper()
        if not other or other == exclude:
            continue
        raw = row.get("score")
        if raw is None:
            continue
        score = clamp_score(raw)
        tag = rating_from_score(score)
        lines.append(f"- {other} {score:+d} ({tag})")
        if len(lines) >= DESK_SCORES_LIMIT:
            break
    if not lines:
        return ""
    return (
        "## Desk scores (other holdings)\n"
        + "\n".join(lines)
        + "\n\nDo not copy a neighbor's 1–5s or this_week_action; place this name relative to them."
    )


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
    thinking = resolve_decision_enable_thinking()
    last_exc: Exception | None = None

    for attempt in range(1, _PRIMARY_ATTEMPTS + 1):
        try:
            llm = _chat_llm(
                primary_name,
                DECISION_TEMPERATURE,
                enable_thinking=thinking,
                thinking_budget=DEFAULT_THINKING_BUDGET if thinking else None,
                json_object=thinking,
                request_timeout=(
                    DEFAULT_THINKING_TIMEOUT_SECONDS if thinking else None
                ),
            )
            result = _invoke_decision_on_llm(
                llm,
                prompt,
                inputs,
                enable_thinking=thinking,
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
    try:
        from services.analysis_knowledge_service import analysis_knowledge_service

        if report_type == "deep":
            priors_md = analysis_knowledge_service.priors_for_deep(
                ticker,
                score=state.get("score"),
                factor_scores=factor_scores,
                key_drivers=list(state.get("key_drivers") or []),
            )
        else:
            priors_md = analysis_knowledge_service.priors_for_core(ticker)
    except Exception as exc:
        logger.warning(f"Priors failed for {ticker}: {exc}")
        priors_md = (
            "## Historical performance priors\n"
            "- Priors unavailable (lookup failed). "
            "Score from current research only."
        )

    try:
        desk_md = desk_scores_markdown_for(ticker)
    except Exception as exc:
        logger.warning(f"Desk scores failed for {ticker}: {exc}")
        desk_md = ""

    context = build_decision_context(
        ticker=ticker,
        live_price=float(live_price),
        factor_scores=factor_scores,
        sections=sections,
        portfolio_markdown=portfolio_md,
        priors_markdown=priors_md,
        desk_scores_markdown=desk_md,
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", DECISION_SYSTEM),
        ("human", """Synthesize the decision for {ticker} based on this analysis.

Horizon: act this week only; intended hold is a few months. this_week_action must
match what to do at/near the live price this week — not a "buy the dip later"
thesis dressed as buy/strong_buy.

For each dimension, list bearish then bullish evidence from the research before
the 1–5. The server computes the numeric score.

{context}

Return the structured rubric (no overall score or rating tag)."""),
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

    score, construction = composite_score(decision)
    rating = rating_from_score(score)
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
        f"AI score {score:+d} · {rating} · {construction}"
        + (f" · gaps: {', '.join(data_flags)}" if data_flags else "")
    )

    reasoning = decision.reasoning or ""
    if construction not in reasoning:
        reasoning = f"### Score construction\n{construction}\n\n{reasoning}".rstrip()

    return {
        "decision_ok": True,
        "error_message": None,
        "rating": rating,
        "score": score,
        "reasoning": reasoning,
        "key_drivers": decision.key_drivers[:5],
        "supporting_headlines": [{"headline": h} for h in decision.supporting_headlines[:5]],
        "entry_levels": entry_levels,
        "factor_scores": factor_scores,
        "dimension_alignment": dimension_alignment,
        "calibration_note": calibration_note,
        "model": used_model,
        "posture": decision.posture,
    }
