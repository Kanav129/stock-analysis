"""Dedicated embedding credentials, separate from Qwen chat."""
from unittest.mock import MagicMock, patch

from config.llm_config import (
    get_chat_llm,
    get_embeddings,
    resolve_embedding_api_key,
    resolve_embedding_base_url,
    resolve_embedding_model,
)


def test_dedicated_embedding_creds_do_not_use_qwen(monkeypatch):
    monkeypatch.setenv("QWEN_API_KEY", "qwen-key")
    monkeypatch.setenv(
        "OPENAI_BASE_URL",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    )
    monkeypatch.setenv("OPENAI_EMBEDDING_API_KEY", "sk-embed")
    monkeypatch.setenv("OPENAI_EMBEDDING_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

    assert resolve_embedding_api_key() == "sk-embed"
    assert resolve_embedding_base_url() == "https://api.openai.com/v1"
    assert resolve_embedding_model() == "text-embedding-3-small"

    with patch("config.llm_config.OpenAIEmbeddings") as ctor:
        ctor.return_value = MagicMock()
        get_embeddings()

    ctor.assert_called_once_with(
        model="text-embedding-3-small",
        api_key="sk-embed",
        base_url="https://api.openai.com/v1",
        check_embedding_ctx_length=False,
        chunk_size=16,
    )


def test_embedding_base_url_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("OPENAI_EMBEDDING_BASE_URL", "https://api.openai.com/v1/")
    assert resolve_embedding_base_url() == "https://api.openai.com/v1"


def test_embedding_base_url_strips_docs_embeddings_path(monkeypatch):
    monkeypatch.setenv(
        "OPENAI_EMBEDDING_BASE_URL",
        "https://api.openai.com/v1/embeddings",
    )
    assert resolve_embedding_base_url() == "https://api.openai.com/v1"


def test_embedding_base_url_adds_v1_for_openai_origin(monkeypatch):
    monkeypatch.setenv("OPENAI_EMBEDDING_BASE_URL", "https://api.openai.com")
    assert resolve_embedding_base_url() == "https://api.openai.com/v1"


def test_embedding_key_defaults_openai_base_url(monkeypatch):
    monkeypatch.delenv("OPENAI_EMBEDDING_BASE_URL", raising=False)
    monkeypatch.delenv("EMBEDDING_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_EMBEDDING_API_KEY", "sk-embed")
    monkeypatch.setenv(
        "OPENAI_BASE_URL",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    )
    assert resolve_embedding_base_url() == "https://api.openai.com/v1"


def test_openai_embedding_url_defaults_model(monkeypatch):
    monkeypatch.delenv("OPENAI_EMBEDDING_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_EMBEDDING_API_KEY", "sk-embed")
    monkeypatch.setenv("OPENAI_EMBEDDING_BASE_URL", "https://api.openai.com/v1")
    assert resolve_embedding_model() == "text-embedding-3-small"


def test_openai_url_ignores_leftover_qwen_embedding_model(monkeypatch):
    monkeypatch.setenv("OPENAI_EMBEDDING_API_KEY", "sk-embed")
    monkeypatch.setenv("OPENAI_EMBEDDING_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-v4")
    assert resolve_embedding_model() == "text-embedding-3-small"


def test_falls_back_to_chat_creds_without_embedding_key(monkeypatch):
    monkeypatch.delenv("OPENAI_EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_EMBEDDING_BASE_URL", raising=False)
    monkeypatch.delenv("EMBEDDING_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_EMBEDDING_MODEL", raising=False)
    monkeypatch.setenv("QWEN_API_KEY", "qwen-key")
    monkeypatch.setenv(
        "OPENAI_BASE_URL",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    )

    assert resolve_embedding_api_key() == "qwen-key"
    assert resolve_embedding_base_url().startswith("https://dashscope-intl")
    assert resolve_embedding_model() == "text-embedding-v4"


def test_chat_llm_ignores_embedding_creds(monkeypatch):
    monkeypatch.setenv("QWEN_API_KEY", "qwen-key")
    monkeypatch.setenv(
        "OPENAI_BASE_URL",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    )
    monkeypatch.setenv("OPENAI_EMBEDDING_API_KEY", "sk-embed")
    monkeypatch.setenv("OPENAI_EMBEDDING_BASE_URL", "https://api.openai.com/v1")

    with patch("config.llm_config.ChatOpenAI") as ctor:
        ctor.return_value = MagicMock()
        get_chat_llm()

    kwargs = ctor.call_args.kwargs
    assert kwargs["api_key"] == "qwen-key"
    assert kwargs["base_url"] == "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
