"""Live job-thinking sink (tokens + node excerpts). No LLM calls."""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from contextvars import ContextVar, Token
from typing import Any

THINKING_MAX_CHARS = 1200
EXCERPT_MAX_CHARS = 800
THINKING_THROTTLE_SECONDS = 0.4

STAGE_SECTION_KEYS = {
    "gather_prices": "market",
    "gather_fundamentals": "fundamentals",
    "gather_news": "news",
    "gather_sentiment": "sentiment",
    "gather_catalysts": "catalysts",
    "gather_flows": "flows",
    "gather_policy": "policy",
    "gather_lockup": "lockup",
    "run_kronos": "kronos",
}

_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_RE = re.compile(r"[#*_`>~]+")
_WS_RE = re.compile(r"\s+")

_sink: ContextVar[Callable[..., None] | None] = ContextVar(
    "llm_progress_sink", default=None
)


def set_thinking_sink(fn: Callable[..., None] | None) -> Token:
    return _sink.set(fn)


def reset_thinking_sink(token: Token) -> None:
    _sink.reset(token)


def has_thinking_sink() -> bool:
    return _sink.get() is not None


def emit_thinking(text: str, *, flush: bool = False) -> None:
    sink = _sink.get()
    if sink is None or not text:
        return
    sink(text, flush=flush)


def make_throttled_sink(
    write: Callable[[str], None],
    min_interval: float = THINKING_THROTTLE_SECONDS,
) -> Callable[..., None]:
    last: list[float | None] = [None]

    def emit(text: str, *, flush: bool = False) -> None:
        if not text:
            return
        now = time.monotonic()
        if (
            not flush
            and last[0] is not None
            and (now - last[0]) < min_interval
        ):
            return
        last[0] = now
        write(text[-THINKING_MAX_CHARS:])

    return emit


def message_text(result: Any) -> str:
    content = getattr(result, "content", result)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text") or ""))
        return "".join(parts)
    if content is None:
        return ""
    return str(content)


def _plain(text: str) -> str:
    text = _LINK_RE.sub(r"\1", text)
    text = _MD_RE.sub("", text)
    return _WS_RE.sub(" ", text).strip()


def thinking_excerpt(
    stage_label: str,
    payload: dict[str, Any] | None,
    *,
    stage: str | None = None,
) -> str | None:
    if not payload:
        return None
    text = ""
    sections = payload.get("sections_markdown")
    if isinstance(sections, dict) and sections:
        key = STAGE_SECTION_KEYS.get(stage or "")
        if key and sections.get(key):
            text = str(sections[key])
        else:
            for value in sections.values():
                if value:
                    text = str(value)
                    break
    if not text and payload.get("reasoning"):
        text = str(payload["reasoning"])
    if not text and payload.get("key_drivers"):
        drivers = payload["key_drivers"]
        if isinstance(drivers, list):
            text = "; ".join(str(d) for d in drivers[:5] if d)
    if not text:
        return None
    plain = _plain(text)[:EXCERPT_MAX_CHARS]
    if not plain:
        return None
    label = (stage_label or "").strip() or "Model"
    return f"{label} — {plain}"
