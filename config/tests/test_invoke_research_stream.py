from unittest.mock import MagicMock, patch

from config.llm_config import invoke_research_llm
from services.llm_progress import reset_thinking_sink, set_thinking_sink


@patch("config.llm_config.call_with_retry_then_fallback")
def test_invoke_research_uses_invoke_without_sink(mock_call):
    llm = MagicMock()
    chain = MagicMock()
    chain.invoke.return_value = "ok"
    prompt = MagicMock()
    prompt.__or__.return_value = chain
    mock_call.side_effect = lambda **kwargs: (kwargs["call"](llm), "m")

    result, _ = invoke_research_llm(prompt, {"ticker": "AAPL"})
    assert result == "ok"
    chain.invoke.assert_called_once()
    chain.stream.assert_not_called()


@patch("config.llm_config.call_with_retry_then_fallback")
def test_invoke_research_streams_when_sink_set(mock_call):
    llm = MagicMock()
    first = MagicMock()
    first.content = "Hel"
    second = MagicMock()
    second.content = "lo"
    # accumulated + chunk
    first.__add__.return_value = second
    chain = MagicMock()
    chain.stream.return_value = [first, second]
    prompt = MagicMock()
    prompt.__or__.return_value = chain
    mock_call.side_effect = lambda **kwargs: (kwargs["call"](llm), "m")

    seen: list[str] = []

    def sink(text: str, *, flush: bool = False) -> None:
        seen.append(text)

    token = set_thinking_sink(sink)
    try:
        result, _ = invoke_research_llm(prompt, {"ticker": "AAPL"})
    finally:
        reset_thinking_sink(token)

    assert result is second
    chain.stream.assert_called_once()
    chain.invoke.assert_not_called()
    assert seen
    assert seen[-1] == "lo"
