from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage

from evals.decision_scoring.invoke_decision import invoke_decision
from rag_graphs.research_graph.nodes.synthesize_decision import DecisionOutput


VALID_PAYLOAD = {
    "rating": "BUY",
    "score": 55,
    "reasoning": "Momentum and earnings support upside.",
    "key_drivers": ["earnings", "momentum"],
    "supporting_headlines": ["Company raises guidance"],
    "entry": 100.0,
    "stop": 92.0,
    "target": 120.0,
    "position_note": "Build gradually.",
    "posture": "bullish",
}


@patch("evals.decision_scoring.invoke_decision.resolve_analysis_model")
@patch("evals.decision_scoring.invoke_decision._chat_llm")
def test_function_calling_returns_validated_structure(mock_chat_llm, mock_model):
    mock_model.return_value = "analysis-model"
    llm = MagicMock()
    structured = MagicMock()
    structured.invoke.return_value = {
        "raw": AIMessage(content=""),
        "parsed": DecisionOutput.model_validate(VALID_PAYLOAD),
        "parsing_error": None,
    }
    llm.with_structured_output.return_value = structured
    mock_chat_llm.return_value = llm

    result = invoke_decision(
        system_prompt="Return a decision.",
        temperature=0.25,
        enable_thinking=False,
        ticker="ACME",
        context="Research context",
    )

    assert result.call_ok
    assert result.schema_method == "function_calling"
    assert result.structure.parsed_ok
    assert result.model == "analysis-model"
    assert result.raw_error is None
    llm.with_structured_output.assert_called_once_with(
        DecisionOutput,
        method="function_calling",
        include_raw=True,
    )
    mock_chat_llm.assert_called_once_with(
        "analysis-model",
        0.25,
        enable_thinking=False,
    )


@patch("evals.decision_scoring.invoke_decision.resolve_analysis_model")
@patch("evals.decision_scoring.invoke_decision._chat_llm")
def test_thinking_tool_choice_failure_falls_back_to_json_parse(
    mock_chat_llm,
    mock_model,
):
    mock_model.return_value = "thinking-model"
    llm = MagicMock()
    llm.with_structured_output.side_effect = RuntimeError(
        "tool_choice is unsupported when thinking is enabled"
    )
    llm.invoke.return_value = AIMessage(
        content=f"```json\n{DecisionOutput.model_validate(VALID_PAYLOAD).model_dump_json()}\n```"
    )
    mock_chat_llm.return_value = llm

    result = invoke_decision(
        system_prompt="Return a decision.",
        temperature=0.4,
        enable_thinking=True,
        ticker="ACME",
        context="Research context",
    )

    assert result.call_ok
    assert result.schema_method == "json_parse"
    assert result.structure.parsed_ok
    assert result.model == "thinking-model"
    assert "tool_choice" in (result.raw_error or "")
    llm.invoke.assert_called_once()
