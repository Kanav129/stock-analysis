from __future__ import annotations

from unittest.mock import MagicMock

from services.llm_progress import (
    THINKING_MAX_CHARS,
    emit_thinking,
    has_thinking_sink,
    make_throttled_sink,
    message_text,
    reset_thinking_sink,
    set_thinking_sink,
    thinking_excerpt,
)


def test_thinking_excerpt_prefers_mapped_section():
    payload = {
        "sections_markdown": {
            "news": "## Headlines\nApple **beats** [estimates](http://x).",
            "market": "ignored",
        }
    }
    out = thinking_excerpt("News / macro", payload, stage="gather_news")
    assert out is not None
    assert out.startswith("News / macro — ")
    assert "Apple beats estimates" in out
    assert "ignored" not in out


def test_thinking_excerpt_uses_reasoning_and_drivers():
    assert thinking_excerpt(
        "Decision synthesis",
        {"reasoning": "Mild **buy** lean on RSI."},
        stage="synthesize_decision",
    ) == "Decision synthesis — Mild buy lean on RSI."
    out = thinking_excerpt(
        "Decision",
        {"key_drivers": ["RSI oversold", "earnings beat"]},
    )
    assert out == "Decision — RSI oversold; earnings beat"


def test_thinking_excerpt_empty_payload():
    assert thinking_excerpt("News", None) is None
    assert thinking_excerpt("News", {}) is None


def test_thinking_excerpt_caps_length():
    payload = {"reasoning": "word " * 500}
    out = thinking_excerpt("Decision", payload)
    assert out is not None
    assert len(out) < 850


def test_throttle_skips_within_interval(monkeypatch):
    writes: list[str] = []
    clock = {"t": 0.0}
    monkeypatch.setattr("services.llm_progress.time.monotonic", lambda: clock["t"])
    emit = make_throttled_sink(writes.append, min_interval=0.4)
    emit("a")
    clock["t"] = 0.1
    emit("ab")
    clock["t"] = 0.5
    emit("abc")
    assert writes == ["a", "abc"]


def test_throttle_flush_writes_immediately(monkeypatch):
    writes: list[str] = []
    clock = {"t": 0.0}
    monkeypatch.setattr("services.llm_progress.time.monotonic", lambda: clock["t"])
    emit = make_throttled_sink(writes.append, min_interval=0.4)
    emit("a")
    clock["t"] = 0.05
    emit("ab", flush=True)
    assert writes == ["a", "ab"]


def test_throttle_caps_length():
    writes: list[str] = []
    emit = make_throttled_sink(writes.append, min_interval=0)
    emit("x" * (THINKING_MAX_CHARS + 50))
    assert len(writes[0]) == THINKING_MAX_CHARS


def test_emit_thinking_noops_without_sink():
    emit_thinking("hello")
    assert has_thinking_sink() is False


def test_emit_thinking_forwards_to_sink():
    seen: list[tuple[str, bool]] = []

    def sink(text: str, *, flush: bool = False) -> None:
        seen.append((text, flush))

    token = set_thinking_sink(sink)
    try:
        emit_thinking("hello", flush=True)
        assert has_thinking_sink() is True
    finally:
        reset_thinking_sink(token)
    assert seen == [("hello", True)]
    assert has_thinking_sink() is False


def test_message_text_from_chunk():
    msg = MagicMock()
    msg.content = "Hello"
    assert message_text(msg) == "Hello"
    msg.content = [{"type": "text", "text": "Hi "}, {"type": "text", "text": "there"}]
    assert message_text(msg) == "Hi there"
