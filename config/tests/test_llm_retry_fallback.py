"""Retry primary model, then cross-role + env fallbacks."""
from unittest.mock import MagicMock, patch

import pytest

from config.llm_config import call_with_retry_then_fallback


@patch("config.llm_config._record_usage")
@patch("config.llm_config.resolve_env_fallback_models", return_value=[])
@patch("config.llm_config._chat_llm")
@patch("config.llm_config.get_analysis_llm")
@patch("config.llm_config.resolve_analysis_fallbacks", return_value=["deepseek/deepseek-v4-flash"])
@patch("config.llm_config.resolve_analysis_model", return_value="openai/gpt-4o")
def test_retries_primary_before_fallback(mock_model, mock_fb, mock_analysis, mock_chat, mock_env, mock_rec):
    primary = MagicMock(name="analysis")
    fallback = MagicMock(name="research-fb")
    mock_analysis.return_value = primary
    mock_chat.return_value = fallback

    calls: list[str] = []

    def call(llm):
        calls.append(llm._mock_name)
        if len(calls) < 3:
            raise RuntimeError(f"fail-{len(calls)}")
        return "ok"

    result, used = call_with_retry_then_fallback(
        role="analysis", temperature=0.25, call=call
    )
    assert result == "ok"
    assert used == "deepseek/deepseek-v4-flash"
    assert calls == ["analysis", "analysis", "research-fb"]
    assert mock_analysis.call_count == 2
    mock_chat.assert_called_once_with(
        "deepseek/deepseek-v4-flash", 0.25, enable_thinking=False
    )


@patch("config.llm_config._record_usage")
@patch("config.llm_config.resolve_env_fallback_models", return_value=[])
@patch("config.llm_config.get_research_llm")
@patch("config.llm_config.get_analysis_llm")
@patch("config.llm_config.resolve_analysis_fallbacks", return_value=["deepseek/deepseek-v4-flash"])
@patch("config.llm_config.resolve_analysis_model", return_value="openai/gpt-4o")
def test_succeeds_on_primary_retry_without_fallback(
    mock_model, mock_fb, mock_analysis, mock_research, mock_env, mock_rec
):
    primary = MagicMock(name="analysis")
    mock_analysis.return_value = primary

    calls = {"n": 0}

    def call(llm):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return "recovered"

    result, used = call_with_retry_then_fallback(
        role="analysis", temperature=0.25, call=call
    )
    assert result == "recovered"
    assert used == "openai/gpt-4o"
    mock_research.assert_not_called()


@patch("config.llm_config._record_usage")
@patch("config.llm_config.resolve_env_fallback_models", return_value=[])
@patch("config.llm_config._chat_llm")
@patch("config.llm_config.get_research_llm")
@patch("config.llm_config.resolve_research_fallbacks", return_value=["openai/gpt-4o"])
@patch("config.llm_config.resolve_research_model", return_value="deepseek/deepseek-v4-flash")
def test_research_retries_then_falls_back_to_analysis(
    mock_model, mock_fb, mock_research, mock_chat, mock_env, mock_rec
):
    research = MagicMock(name="research")
    analysis = MagicMock(name="analysis-fb")
    mock_research.return_value = research
    mock_chat.return_value = analysis

    calls: list[str] = []

    def call(llm):
        calls.append(llm._mock_name)
        if len(calls) < 3:
            raise RuntimeError("fail")
        return "ok"

    result, used = call_with_retry_then_fallback(
        role="research", temperature=0.2, call=call
    )
    assert result == "ok"
    assert used == "openai/gpt-4o"
    assert calls == ["research", "research", "analysis-fb"]
    mock_chat.assert_called_once_with("openai/gpt-4o", 0.2, enable_thinking=None)


@patch("config.llm_config._record_usage")
@patch("config.llm_config.resolve_env_fallback_models", return_value=[])
@patch("config.llm_config.get_analysis_llm")
@patch("config.llm_config.resolve_analysis_fallbacks", return_value=[])
@patch("config.llm_config.resolve_analysis_model", return_value="openai/gpt-4o")
def test_raises_when_primary_retries_exhausted_and_no_fallback(
    mock_model, mock_fb, mock_analysis, mock_env, mock_rec
):
    mock_analysis.return_value = MagicMock(name="analysis")

    def call(llm):
        raise RuntimeError("always")

    with pytest.raises(RuntimeError, match="always"):
        call_with_retry_then_fallback(role="analysis", temperature=0.25, call=call)
    assert mock_analysis.call_count == 2


@patch("config.llm_config._record_usage")
@patch("config.llm_config._chat_llm")
@patch("config.llm_config.get_analysis_llm")
@patch(
    "config.llm_config.resolve_env_fallback_models",
    return_value=["deepseek/deepseek-v4-pro", "deepseek/deepseek-v4-flash"],
)
@patch(
    "config.llm_config.resolve_analysis_fallbacks",
    return_value=["openai/gpt-5.6-luna"],
)
@patch("config.llm_config.resolve_analysis_model", return_value="openai/gpt-5.6-luna-pro")
def test_falls_back_to_env_models_when_cross_role_fails(
    mock_model, mock_cross, mock_env, mock_analysis, mock_chat, mock_rec
):
    """Simulates HK region block: DB OpenAI models fail, .env DeepSeek succeeds."""
    primary = MagicMock(name="analysis")
    cross_fb = MagicMock(name="cross-fb")
    env_fb = MagicMock(name="env-fb")
    mock_analysis.return_value = primary
    mock_chat.side_effect = [cross_fb, env_fb]

    calls: list[str] = []

    def call(llm):
        calls.append(llm._mock_name)
        if len(calls) < 4:
            raise RuntimeError(f"region-blocked-{len(calls)}")
        return "deepseek-ok"

    result, used = call_with_retry_then_fallback(
        role="analysis", temperature=0.25, call=call
    )
    assert result == "deepseek-ok"
    assert used == "deepseek/deepseek-v4-pro"
    assert calls == ["analysis", "analysis", "cross-fb", "env-fb"]
    assert mock_chat.call_args_list[0].args == ("openai/gpt-5.6-luna", 0.25)
    assert mock_chat.call_args_list[0].kwargs.get("enable_thinking") is False
    assert mock_chat.call_args_list[1].args == ("deepseek/deepseek-v4-pro", 0.25)
    assert mock_chat.call_args_list[1].kwargs.get("enable_thinking") is False
