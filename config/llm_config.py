import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

load_dotenv()


def _setting(key: str, env_keys: list[str], default: str = "") -> str:
    """Prefer DB app_settings, then env vars."""
    try:
        from services.settings_service import SettingsService

        stored = SettingsService().get_raw(key)
        if stored:
            return stored
    except Exception:
        pass
    for env_key in env_keys:
        val = os.getenv(env_key)
        if val:
            return val
    return default


def resolve_openrouter_api_key() -> str:
    return _setting(
        "openrouter_api_key",
        ["OPENROUTER_API_KEY", "OPENAI_API_KEY"],
        "",
    )


def resolve_analysis_model() -> str:
    return _setting(
        "analysis_model",
        ["ANALYSIS_MODEL", "OPENAI_MODEL"],
        "deepseek/deepseek-v4-pro",
    )


def resolve_research_model() -> str:
    return _setting(
        "research_model",
        ["RESEARCH_MODEL", "ANALYSIS_MODEL"],
        "deepseek/deepseek-v4-flash",
    )


def _openrouter_api_key() -> str:
    return resolve_openrouter_api_key()


def get_chat_llm(temperature: float = 0) -> ChatOpenAI:
    """Chat model configured for OpenRouter (OpenAI-compatible API)."""
    return ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "openai/gpt-4o-mini"),
        temperature=temperature,
        api_key=_openrouter_api_key(),
        base_url=os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
    )


def get_embeddings() -> OpenAIEmbeddings:
    """Embedding model configured for OpenRouter (OpenAI-compatible API)."""
    return OpenAIEmbeddings(
        model=os.getenv("OPENAI_EMBEDDING_MODEL", "openai/text-embedding-3-small"),
        api_key=_openrouter_api_key(),
        base_url=os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
    )


def get_analysis_llm(temperature: float = 0.2) -> ChatOpenAI:
    """Stronger model for final decision synthesis (ANALYSIS_MODEL)."""
    return ChatOpenAI(
        model=resolve_analysis_model(),
        temperature=temperature,
        api_key=_openrouter_api_key(),
        base_url=os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
    )


def get_research_llm(temperature: float = 0.2) -> ChatOpenAI:
    """Cheaper model for report section generation (RESEARCH_MODEL)."""
    return ChatOpenAI(
        model=resolve_research_model(),
        temperature=temperature,
        api_key=_openrouter_api_key(),
        base_url=os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
    )
