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


@patch("config.llm_config._openrouter_api_key", return_value="test-key")
@patch("config.llm_config.resolve_analysis_model", return_value="openai/gpt-4o")
def test_get_analysis_llm_has_no_openrouter_model_list(mock_a, mock_key):
    """Model fallbacks are app-level (retry then fallback), not OpenRouter models[]."""
    llm = get_analysis_llm()
    assert llm.model_name == "openai/gpt-4o" or llm.model == "openai/gpt-4o"
    assert not getattr(llm, "extra_body", None)


@patch("config.llm_config._openrouter_api_key", return_value="test-key")
@patch("config.llm_config.resolve_research_model", return_value="deepseek/deepseek-v4-flash")
def test_get_research_llm_has_no_openrouter_model_list(mock_r, mock_key):
    llm = get_research_llm()
    assert llm.model_name == "deepseek/deepseek-v4-flash" or llm.model == "deepseek/deepseek-v4-flash"
    assert not getattr(llm, "extra_body", None)


@patch.dict("os.environ", {"ANALYSIS_MODEL": "deepseek/deepseek-v4-pro", "RESEARCH_MODEL": "deepseek/deepseek-v4-flash"})
def test_env_fallback_models_skip_primary():
    assert resolve_env_fallback_models("openai/gpt-5.6-luna-pro") == [
        "deepseek/deepseek-v4-pro",
        "deepseek/deepseek-v4-flash",
    ]


@patch.dict("os.environ", {"ANALYSIS_MODEL": "deepseek/deepseek-v4-pro", "RESEARCH_MODEL": "deepseek/deepseek-v4-pro"})
def test_env_fallback_deduplicates_identical_models():
    assert resolve_env_fallback_models("openai/gpt-5.6-luna-pro") == ["deepseek/deepseek-v4-pro"]
