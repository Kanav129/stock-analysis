"""Cross-role fallback model resolution (used after primary retries)."""
from unittest.mock import patch

from config.llm_config import (
    get_analysis_llm,
    get_research_llm,
    resolve_analysis_fallbacks,
    resolve_env_fallback_models,
    resolve_research_fallbacks,
)


@patch("config.llm_config.resolve_research_model", return_value="deepseek/deepseek-v4-flash")
@patch("config.llm_config.resolve_analysis_model", return_value="openai/gpt-4o")
def test_analysis_falls_back_to_research(mock_a, mock_r):
    assert resolve_analysis_fallbacks() == ["deepseek/deepseek-v4-flash"]


@patch("config.llm_config.resolve_research_model", return_value="deepseek/deepseek-v4-flash")
@patch("config.llm_config.resolve_analysis_model", return_value="openai/gpt-4o")
def test_research_falls_back_to_analysis(mock_a, mock_r):
    assert resolve_research_fallbacks() == ["openai/gpt-4o"]


@patch("config.llm_config.resolve_research_model", return_value="openai/gpt-4o")
@patch("config.llm_config.resolve_analysis_model", return_value="openai/gpt-4o")
def test_no_fallback_when_models_identical(mock_a, mock_r):
    assert resolve_analysis_fallbacks() == []
    assert resolve_research_fallbacks() == []


@patch("config.llm_config._llm_api_key", return_value="test-key")
@patch("config.llm_config.resolve_analysis_model", return_value="qwen3.7-max")
def test_get_analysis_llm_has_no_openrouter_model_list(mock_a, mock_key):
    """Model fallbacks are app-level (retry then fallback), not provider model lists."""
    llm = get_analysis_llm()
    assert llm.model_name == "qwen3.7-max" or llm.model == "qwen3.7-max"
    # Thinking must be off so Qwen accepts tool_choice=required for structured output.
    assert getattr(llm, "extra_body", None) == {"enable_thinking": False}


@patch("config.llm_config._llm_api_key", return_value="test-key")
@patch("config.llm_config.resolve_research_model", return_value="qwen3.7-flash")
def test_get_research_llm_has_no_openrouter_model_list(mock_r, mock_key):
    llm = get_research_llm()
    assert llm.model_name == "qwen3.7-flash" or llm.model == "qwen3.7-flash"
    # Research is free-text; do not force thinking off by default.
    assert not getattr(llm, "extra_body", None)


@patch.dict("os.environ", {"ANALYSIS_MODEL": "qwen3.7-max", "RESEARCH_MODEL": "qwen3.7-flash"})
def test_env_fallback_models_skip_primary():
    assert resolve_env_fallback_models("openai/gpt-4o") == [
        "qwen3.7-max",
        "qwen3.7-flash",
    ]


@patch.dict("os.environ", {"ANALYSIS_MODEL": "qwen3.7-max", "RESEARCH_MODEL": "qwen3.7-max"})
def test_env_fallback_deduplicates_identical_models():
    assert resolve_env_fallback_models("openai/gpt-4o") == ["qwen3.7-max"]
