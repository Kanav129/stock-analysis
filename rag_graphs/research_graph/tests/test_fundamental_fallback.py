"""Previous-report fallback must see null fundamentals, not only a missing overview key."""
from unittest.mock import MagicMock, patch

from rag_graphs.research_graph.nodes.synthesize_decision import (
    DecisionOutput,
    DimensionRating,
    synthesize_decision,
)


def _dim(level: int) -> DimensionRating:
    return DimensionRating(bearish=["risk"], bullish=["ok"], score_1_to_5=level)


def _decision() -> DecisionOutput:
    return DecisionOutput(
        bearish_factors=["valuation", "extension"],
        bullish_factors=["growth", "cash flow"],
        fundamental_health=_dim(3),
        valuation=_dim(3),
        technical_momentum=_dim(3),
        sentiment_and_news=_dim(3),
        this_week_setup=_dim(3),
        this_week_action="hold",
        reasoning="ok",
        key_drivers=["growth"],
        supporting_headlines=["headline"],
        entry=None,
        stop=None,
        target=None,
        position_note="Hold.",
        posture="held",
    )


def _llm() -> MagicMock:
    decision = _decision()
    structured = MagicMock()
    structured.return_value = decision
    structured.invoke.return_value = decision
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


def _empty_fetch_state(**overrides):
    state = {
        "ticker": "NVDA",
        "report_type": "core",
        "live_price": 180.0,
        "fundamental_data": {
            "overview": {
                "forward_pe": None,
                "beta": None,
                "sector": None,
            },
            "revenue_growth_pct": None,
            "gross_margin_pct": None,
            "fcf_margin_pct": None,
            "cash_exceeds_debt": None,
        },
        "market_data": {},
        "sentiment_data": {},
        "factor_scores": {},
        "sections_markdown": {},
    }
    state.update(overrides)
    return state


_GOOD = {
    "forward_pe": 28.0,
    "beta": 1.6,
    "revenue_growth_pct": 22.5,
    "gross_margin_pct": 72.0,
    "fcf_margin_pct": 25.0,
    "cash_exceeds_debt": True,
    "as_of": "2026-09-29",
}


@patch("services.analysis_knowledge_service.analysis_knowledge_service.priors_for_core", return_value="priors")
@patch(
    "rag_graphs.research_graph.nodes.synthesize_decision.portfolio_markdown_for",
    return_value="## Personal Portfolio\n- held",
)
@patch("rag_graphs.research_graph.nodes.synthesize_decision._chat_llm")
@patch("rag_graphs.research_graph.nodes.synthesize_decision.resolve_analysis_model", return_value="qwen3.8-max")
@patch("rag_graphs.research_graph.nodes.synthesize_decision._record_usage")
@patch("rag_graphs.research_graph.nodes.synthesize_decision._load_last_good_fundamentals")
def test_null_overview_reuses_previous_inputs_and_date(
    mock_load, _usage, _model, mock_chat, _port, _priors
):
    mock_chat.return_value = _llm()
    mock_load.return_value = None
    state = _empty_fetch_state(
        factor_scores={
            "growth": 0,
            "quality": 0,
            "_inputs": dict(_GOOD),
        }
    )

    out = synthesize_decision(state)  # type: ignore[arg-type]

    mock_load.assert_not_called()
    assert out["factor_scores"]["growth"] == 75
    assert out["factor_scores"]["quality"] > 0
    assert out["factor_scores"]["_inputs"]["as_of"] == "2026-09-29"
    assert out["factor_scores"]["_inputs"]["revenue_growth_pct"] == 22.5
    assert "2026-09-29" in out["calibration_note"]
    assert "data missing" not in out["calibration_note"]


@patch("services.analysis_knowledge_service.analysis_knowledge_service.priors_for_core", return_value="priors")
@patch(
    "rag_graphs.research_graph.nodes.synthesize_decision.portfolio_markdown_for",
    return_value="## Personal Portfolio\n- held",
)
@patch("rag_graphs.research_graph.nodes.synthesize_decision._chat_llm")
@patch("rag_graphs.research_graph.nodes.synthesize_decision.resolve_analysis_model", return_value="qwen3.8-max")
@patch("rag_graphs.research_graph.nodes.synthesize_decision._record_usage")
@patch("rag_graphs.research_graph.nodes.synthesize_decision._load_last_good_fundamentals")
def test_zeroed_state_scores_fall_through_to_stored_report(
    mock_load, _usage, _model, mock_chat, _port, _priors
):
    """join_core writes today's 0-default scores before synthesize. Ignore them."""
    mock_chat.return_value = _llm()
    mock_load.return_value = {"inputs": dict(_GOOD), "as_of": "2026-09-29"}
    state = _empty_fetch_state(
        factor_scores={
            "growth": 0,
            "quality": 0,
            "_inputs": {
                "forward_pe": None,
                "beta": None,
                "revenue_growth_pct": 0,
                "gross_margin_pct": 0,
                "fcf_margin_pct": 0,
                "cash_exceeds_debt": False,
            },
        }
    )

    out = synthesize_decision(state)  # type: ignore[arg-type]

    mock_load.assert_called_once_with("NVDA", "core")
    assert out["factor_scores"]["growth"] == 75
    assert out["factor_scores"]["_inputs"]["as_of"] == "2026-09-29"
    assert out["factor_scores"]["_inputs"]["gross_margin_pct"] == 72.0


@patch("services.analysis_knowledge_service.analysis_knowledge_service.priors_for_core", return_value="priors")
@patch(
    "rag_graphs.research_graph.nodes.synthesize_decision.portfolio_markdown_for",
    return_value="## Personal Portfolio\n- held",
)
@patch("rag_graphs.research_graph.nodes.synthesize_decision._chat_llm")
@patch("rag_graphs.research_graph.nodes.synthesize_decision.resolve_analysis_model", return_value="qwen3.8-max")
@patch("rag_graphs.research_graph.nodes.synthesize_decision._record_usage")
@patch("rag_graphs.research_graph.nodes.synthesize_decision._load_last_good_fundamentals", return_value=None)
def test_missing_with_no_history_is_neutral_not_zero(
    _load, _usage, _model, mock_chat, _port, _priors
):
    mock_chat.return_value = _llm()

    out = synthesize_decision(_empty_fetch_state())  # type: ignore[arg-type]

    scores = out["factor_scores"]
    assert scores["growth"] == 50
    assert scores["quality"] == 50
    assert scores["growth"] != 0
    assert "revenue_growth_pct" in scores["data_missing"]
    assert "data missing: " in out["calibration_note"]
