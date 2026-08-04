import os
from collections.abc import Callable
from typing import Literal, TypeVar

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from utils.logger import logger

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


def resolve_analysis_fallbacks() -> list[str]:
    """When ANALYSIS_MODEL fails (after retry), try RESEARCH_MODEL (if different)."""
    primary = resolve_analysis_model().strip()
    research = resolve_research_model().strip()
    if research and research != primary:
        return [research]
    return []


def resolve_research_fallbacks() -> list[str]:
    """When RESEARCH_MODEL fails (after retry), try ANALYSIS_MODEL (if different)."""
    primary = resolve_research_model().strip()
    analysis = resolve_analysis_model().strip()
    if analysis and analysis != primary:
        return [analysis]
    return []


def _env_model(*env_keys: str) -> str:
    """Read model name from env only (never DB settings)."""
    for key in env_keys:
        val = os.getenv(key)
        if val and val.strip():
            return val.strip()
    return ""


def resolve_env_fallback_models(primary: str) -> list[str]:
    """Env-only models when DB-configured models fail (e.g. region-blocked OpenAI)."""
    primary = primary.strip()
    candidates = [
        _env_model("ANALYSIS_MODEL", "OPENAI_MODEL"),
        _env_model("RESEARCH_MODEL", "ANALYSIS_MODEL"),
    ]
    chain: list[str] = []
    for model in candidates:
        if model and model != primary and model not in chain:
            chain.append(model)
    return chain


def _fallback_chain(role: Literal["analysis", "research"], primary_name: str) -> list[str]:
    """Cross-role configured fallbacks, then env-only models."""
    if role == "analysis":
        cross = resolve_analysis_fallbacks()
    else:
        cross = resolve_research_fallbacks()
    chain: list[str] = []
    for model in cross:
        if model and model not in chain:
            chain.append(model)
    for model in resolve_env_fallback_models(primary_name):
        if model not in chain:
            chain.append(model)
    return chain


def _openrouter_api_key() -> str:
    return resolve_openrouter_api_key()


def _openrouter_base_url() -> str:
    return os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")


def _chat_llm(model: str, temperature: float) -> ChatOpenAI:
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=_openrouter_api_key(),
        base_url=_openrouter_base_url(),
    )


def get_chat_llm(temperature: float = 0) -> ChatOpenAI:
    """Chat model configured for OpenRouter (OpenAI-compatible API)."""
    return ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "openai/gpt-4o-mini"),
        temperature=temperature,
        api_key=_openrouter_api_key(),
        base_url=_openrouter_base_url(),
    )


def get_embeddings() -> OpenAIEmbeddings:
    """Embedding model configured for OpenRouter (OpenAI-compatible API)."""
    return OpenAIEmbeddings(
        model=os.getenv("OPENAI_EMBEDDING_MODEL", "openai/text-embedding-3-small"),
        api_key=_openrouter_api_key(),
        base_url=_openrouter_base_url(),
    )


def get_analysis_llm(temperature: float = 0.2) -> ChatOpenAI:
    """Decision synthesis model (ANALYSIS_MODEL)."""
    return _chat_llm(resolve_analysis_model(), temperature)


def get_research_llm(temperature: float = 0.2) -> ChatOpenAI:
    """Report section model (RESEARCH_MODEL)."""
    return _chat_llm(resolve_research_model(), temperature)


T = TypeVar("T")


def call_with_retry_then_fallback(
    *,
    role: Literal["analysis", "research"],
    temperature: float,
    call: Callable[[ChatOpenAI], T],
    primary_attempts: int = 2,
) -> tuple[T, str]:
    """Try the primary model (with retries), then fallbacks.

    Order:
    1. Primary model (analysis or research), retried up to primary_attempts
    2. Cross-role configured fallback (analysis↔research from settings)
    3. Env-only models (ANALYSIS_MODEL / RESEARCH_MODEL from .env, skip DB)
    """
    if role == "analysis":
        primary_name = resolve_analysis_model()
        make_primary = get_analysis_llm
    else:
        primary_name = resolve_research_model()
        make_primary = get_research_llm

    last_exc: Exception | None = None
    for attempt in range(1, primary_attempts + 1):
        try:
            return call(make_primary(temperature)), primary_name
        except Exception as exc:
            last_exc = exc
            logger.warning(
                f"{role} LLM ({primary_name}) attempt {attempt}/{primary_attempts} failed: {exc}"
            )

    for fallback_name in _fallback_chain(role, primary_name):
        try:
            result = call(_chat_llm(fallback_name, temperature))
            logger.info(f"{role} succeeded via fallback model {fallback_name}")
            return result, fallback_name
        except Exception as exc:
            last_exc = exc
            logger.warning(f"{role} fallback LLM ({fallback_name}) failed: {exc}")

    assert last_exc is not None
    raise last_exc


def invoke_research_llm(
    prompt,
    inputs: dict,
    *,
    temperature: float = 0.2,
) -> tuple[T, str]:
    """Run a research prompt with retry + cross-role + env fallbacks."""

    def call(llm: ChatOpenAI):
        return (prompt | llm).invoke(inputs)

    return call_with_retry_then_fallback(
        role="research",
        temperature=temperature,
        call=call,
    )
