import os
from collections.abc import Callable
from typing import Any, Literal, TypeVar

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from utils.logger import logger

load_dotenv()

DEFAULT_LLM_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
DEFAULT_CHAT_MODEL = "qwen3.7-flash"
DEFAULT_EMBEDDING_MODEL = "text-embedding-v4"
DEFAULT_OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_OPENAI_EMBEDDING_BASE_URL = "https://api.openai.com/v1"
DEFAULT_ANALYSIS_MODEL = "qwen3.7-max"
DEFAULT_RESEARCH_MODEL = "qwen3.7-flash"

_LLM_API_KEY_ENV_KEYS = [
    "QWEN_API_KEY",
    "DASHSCOPE_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
]

_EMBEDDING_API_KEY_ENV_KEYS = [
    "OPENAI_EMBEDDING_API_KEY",
    "EMBEDDING_API_KEY",
]


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


def resolve_llm_api_key() -> str:
    """API key for the configured OpenAI-compatible LLM provider (Qwen / DashScope by default)."""
    return _setting("llm_api_key", _LLM_API_KEY_ENV_KEYS, "")


def resolve_openrouter_api_key() -> str:
    """Back-compat alias for older imports."""
    return resolve_llm_api_key()


def resolve_analysis_model() -> str:
    return _setting(
        "analysis_model",
        ["ANALYSIS_MODEL", "OPENAI_MODEL"],
        DEFAULT_ANALYSIS_MODEL,
    )


def resolve_research_model() -> str:
    return _setting(
        "research_model",
        ["RESEARCH_MODEL", "ANALYSIS_MODEL"],
        DEFAULT_RESEARCH_MODEL,
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


def resolve_llm_base_url() -> str:
    return (os.getenv("OPENAI_BASE_URL") or DEFAULT_LLM_BASE_URL).strip()


def _llm_api_key() -> str:
    return resolve_llm_api_key()


def _llm_base_url() -> str:
    return resolve_llm_base_url()


def _env_first(*env_keys: str) -> str:
    for key in env_keys:
        val = os.getenv(key)
        if val and val.strip():
            return val.strip()
    return ""


def resolve_embedding_api_key() -> str:
    """API key used only for news vector embeddings (not chat/analysis)."""
    return _env_first(*_EMBEDDING_API_KEY_ENV_KEYS) or _llm_api_key()


def _normalize_embedding_base_url(url: str) -> str:
    """SDK clients append `/embeddings`; docs URLs that already include it 400."""
    url = url.strip().rstrip("/")
    if url.endswith("/embeddings"):
        url = url[: -len("/embeddings")].rstrip("/")
    if url in {"https://api.openai.com", "http://api.openai.com"}:
        url = f"{url}/v1"
    return url


def resolve_embedding_base_url() -> str:
    """Base URL used only for embeddings.

    A dedicated embedding key without a URL defaults to OpenAI, so Qwen Lite
    chat credentials are not reused for a model that plan does not include.
    """
    explicit = _env_first("OPENAI_EMBEDDING_BASE_URL", "EMBEDDING_BASE_URL")
    if explicit:
        return _normalize_embedding_base_url(explicit)
    if _env_first(*_EMBEDDING_API_KEY_ENV_KEYS):
        return DEFAULT_OPENAI_EMBEDDING_BASE_URL
    return _normalize_embedding_base_url(_llm_base_url())


_QWEN_ONLY_EMBEDDING_MODELS = frozenset({"text-embedding-v4", "text-embedding-v3"})


def resolve_embedding_model() -> str:
    explicit = _env_first("OPENAI_EMBEDDING_MODEL")
    using_openai = "api.openai.com" in resolve_embedding_base_url()
    if explicit:
        # Leftover DashScope model IDs 404 on api.openai.com.
        if using_openai and explicit.lower() in _QWEN_ONLY_EMBEDDING_MODELS:
            return DEFAULT_OPENAI_EMBEDDING_MODEL
        return explicit
    if using_openai:
        return DEFAULT_OPENAI_EMBEDDING_MODEL
    return DEFAULT_EMBEDDING_MODEL


def _chat_llm(
    model: str,
    temperature: float,
    *,
    enable_thinking: bool | None = None,
) -> ChatOpenAI:
    """Build a ChatOpenAI client.

    Qwen thinking mode rejects tool_choice=required (used by structured output /
    function calling). Pass enable_thinking=False for analysis / tool calls.
    """
    kwargs: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "api_key": _llm_api_key(),
        "base_url": _llm_base_url(),
    }
    if enable_thinking is not None:
        kwargs["extra_body"] = {"enable_thinking": enable_thinking}
    return ChatOpenAI(**kwargs)


def get_chat_llm(temperature: float = 0) -> ChatOpenAI:
    """General chat model (OPENAI_MODEL) for RAG helpers."""
    # Graders use with_structured_output → needs tool_choice; disable thinking.
    return ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", DEFAULT_CHAT_MODEL),
        temperature=temperature,
        api_key=_llm_api_key(),
        base_url=_llm_base_url(),
        extra_body={"enable_thinking": False},
    )


def get_embeddings() -> OpenAIEmbeddings:
    """Embedding model for news vector store.

    Uses OPENAI_EMBEDDING_* credentials when set so indexing can run on a
    separate provider from Qwen chat (Lite plans do not include embeddings).
    """
    return OpenAIEmbeddings(
        model=resolve_embedding_model(),
        api_key=resolve_embedding_api_key(),
        base_url=resolve_embedding_base_url(),
        # Default True sends tiktoken ids; many OpenAI-compatible endpoints
        # (and a copied `/v1/embeddings` base URL) reject that with HTTP 400.
        check_embedding_ctx_length=False,
        chunk_size=16,
    )


def get_analysis_llm(temperature: float = 0.2) -> ChatOpenAI:
    """Decision synthesis model (ANALYSIS_MODEL). Thinking off for structured output."""
    return _chat_llm(resolve_analysis_model(), temperature, enable_thinking=False)


def get_research_llm(temperature: float = 0.2) -> ChatOpenAI:
    """Report section model (RESEARCH_MODEL). Thinking off to cut tokens/latency."""
    return _chat_llm(
        resolve_research_model(),
        temperature,
        enable_thinking=False,
    )


T = TypeVar("T")


def _record_usage(role: Literal["analysis", "research", "other"], model: str, result: Any) -> None:
    try:
        from services.llm_usage_service import LlmUsageService

        LlmUsageService().record_from_result(role=role, model=model, result=result)
    except Exception as exc:
        logger.warning(f"LLM usage tracking skipped: {exc}")


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
            result = call(make_primary(temperature))
            _record_usage(role, primary_name, result)
            return result, primary_name
        except Exception as exc:
            last_exc = exc
            logger.warning(
                f"{role} LLM ({primary_name}) attempt {attempt}/{primary_attempts} failed: {exc}"
            )

    for fallback_name in _fallback_chain(role, primary_name):
        try:
            # Keep thinking off for analysis (structured output) and research (cost/latency).
            result = call(
                _chat_llm(
                    fallback_name,
                    temperature,
                    enable_thinking=False,
                )
            )
            logger.info(f"{role} succeeded via fallback model {fallback_name}")
            _record_usage(role, fallback_name, result)
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
        chain = prompt | llm
        from services.llm_progress import emit_thinking, has_thinking_sink, message_text

        if not has_thinking_sink():
            return chain.invoke(inputs)
        accumulated = None
        for chunk in chain.stream(inputs):
            accumulated = chunk if accumulated is None else accumulated + chunk
            emit_thinking(message_text(accumulated))
        if accumulated is not None:
            emit_thinking(message_text(accumulated), flush=True)
            return accumulated
        return chain.invoke(inputs)

    return call_with_retry_then_fallback(
        role="research",
        temperature=temperature,
        call=call,
    )
