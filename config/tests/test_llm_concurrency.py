"""LLM_MAX_CONCURRENT clamps to 1–2 and serializes overlapping invokes."""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

from config.llm_config import (
    _bind_llm_slot,
    _llm_max_concurrent,
    reset_llm_slot_for_tests,
)


def test_llm_max_concurrent_clamps(monkeypatch):
    monkeypatch.setenv("LLM_MAX_CONCURRENT", "0")
    reset_llm_slot_for_tests()
    assert _llm_max_concurrent() == 1
    monkeypatch.setenv("LLM_MAX_CONCURRENT", "3")
    reset_llm_slot_for_tests()
    assert _llm_max_concurrent() == 2
    monkeypatch.setenv("LLM_MAX_CONCURRENT", "1")
    reset_llm_slot_for_tests()
    assert _llm_max_concurrent() == 1
    monkeypatch.setenv("LLM_MAX_CONCURRENT", "nope")
    reset_llm_slot_for_tests()
    assert _llm_max_concurrent() == 1


def test_slot_serializes_overlapping_invokes(monkeypatch):
    monkeypatch.setenv("LLM_MAX_CONCURRENT", "1")
    reset_llm_slot_for_tests()
    llm = MagicMock()
    in_flight = {"n": 0, "max": 0}
    lock = threading.Lock()

    def slow_invoke(*_args, **_kwargs):
        with lock:
            in_flight["n"] += 1
            in_flight["max"] = max(in_flight["max"], in_flight["n"])
        time.sleep(0.05)
        with lock:
            in_flight["n"] -= 1
        return "ok"

    llm.invoke = slow_invoke
    llm.stream = lambda *a, **k: iter(())
    wrapped = _bind_llm_slot(llm)

    results: list[str] = []

    def run():
        results.append(wrapped.invoke("x"))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results == ["ok", "ok"]
    assert in_flight["max"] == 1
