"""Core decision prompt can request a deep dive without a second LLM call."""
from __future__ import annotations

from unittest.mock import patch

from rag_graphs.research_graph.nodes.synthesize_decision import (
    CORE_DEEP_REQUEST_GUIDANCE,
    DECISION_SYSTEM,
    DecisionOutput,
    DimensionRating,
    decision_system_prompt,
    synthesize_decision,
)


def test_guidance_teaches_deep_sections_and_does_not_pitch_kronos():
    text = CORE_DEEP_REQUEST_GUIDANCE.lower()
    assert "hot money" in text or "flows" in text
    assert "policy" in text
    assert "lockup" in text
    assert "research plan" in text
    assert "trader proposal" in text
    assert "portfolio decision" in text
    assert "kronos" not in text
    assert "forecast" not in text
    assert "request_deep" in CORE_DEEP_REQUEST_GUIDANCE
    assert "empty" in text


def test_core_prompt_includes_guidance_and_base_prompt_stays_shared():
    assert "request_deep" not in DECISION_SYSTEM
    core = decision_system_prompt("core")
    deep = decision_system_prompt("deep")
    assert CORE_DEEP_REQUEST_GUIDANCE in core
    assert CORE_DEEP_REQUEST_GUIDANCE not in deep
    assert deep == DECISION_SYSTEM


def test_decision_output_defaults_deep_request_off():
    decision = _decision()
    assert decision.request_deep is False
    assert decision.request_deep_reason == ""


def _dim(level: int) -> DimensionRating:
    return DimensionRating(bearish=["risk"], bullish=["ok"], score_1_to_5=level)


def _decision(**overrides) -> DecisionOutput:
    payload = {
        "bearish_factors": ["valuation", "extension"],
        "bullish_factors": ["franchise", "cash flow"],
        "fundamental_health": _dim(3),
        "valuation": _dim(3),
        "technical_momentum": _dim(3),
        "sentiment_and_news": _dim(3),
        "this_week_setup": _dim(3),
        "this_week_action": "hold",
        "reasoning": "mixed",
        "key_drivers": ["valuation"],
        "supporting_headlines": ["headline"],
    }
    payload.update(overrides)
    return DecisionOutput(**payload)


def _state(report_type: str) -> dict:
    return {
        "ticker": "AAPL",
        "report_type": report_type,
        "live_price": 100.0,
        "fundamental_data": {},
        "market_data": {},
        "sentiment_data": {},
        "factor_scores": {},
        "sections_markdown": {},
    }


def test_synthesize_core_returns_model_deep_request_and_teaches_prompt():
    decision = _decision(
        request_deep=True,
        request_deep_reason="Policy exposure is material and unanswered.",
    )
    captured: dict = {}

    def _capture(prompt, _inputs):
        captured["system"] = prompt.messages[0].prompt.template
        return decision, "qwen3.8-max"

    with (
        patch(
            "rag_graphs.research_graph.nodes.synthesize_decision._call_decision_llm",
            side_effect=_capture,
        ),
        patch(
            "rag_graphs.research_graph.nodes.synthesize_decision.portfolio_markdown_for",
            return_value="## Personal Portfolio\n- none",
        ),
        patch(
            "rag_graphs.research_graph.nodes.synthesize_decision.desk_scores_markdown_for",
            return_value="",
        ),
        patch(
            "services.analysis_knowledge_service.analysis_knowledge_service.priors_for_core",
            return_value="",
        ),
    ):
        out = synthesize_decision(_state("core"))  # type: ignore[arg-type]

    assert CORE_DEEP_REQUEST_GUIDANCE in captured["system"]
    assert out["decision_ok"] is True
    assert out["deep_request"] == {
        "recommended": True,
        "reason": "Policy exposure is material and unanswered.",
    }


def test_synthesize_deep_does_not_ask_for_another_deep():
    decision = _decision(
        request_deep=True,
        request_deep_reason="Should be ignored on a deep report.",
    )
    captured: dict = {}

    def _capture(prompt, _inputs):
        captured["system"] = prompt.messages[0].prompt.template
        return decision, "qwen3.8-max"

    with (
        patch(
            "rag_graphs.research_graph.nodes.synthesize_decision._call_decision_llm",
            side_effect=_capture,
        ),
        patch(
            "rag_graphs.research_graph.nodes.synthesize_decision.portfolio_markdown_for",
            return_value="## Personal Portfolio\n- none",
        ),
        patch(
            "rag_graphs.research_graph.nodes.synthesize_decision.desk_scores_markdown_for",
            return_value="",
        ),
        patch(
            "services.analysis_knowledge_service.analysis_knowledge_service.priors_for_deep",
            return_value="",
        ),
    ):
        out = synthesize_decision(_state("deep"))  # type: ignore[arg-type]

    assert "request_deep" not in captured["system"]
    assert "deep_request" not in out
