"""KRONOS_ENABLED env flag — skip PyTorch load on low-memory hosts (e.g. Render 512 MB)."""
from __future__ import annotations

import os
from unittest.mock import patch

from rag_graphs.research_graph.nodes.run_kronos import is_kronos_enabled, run_kronos


def test_is_kronos_enabled_defaults_true(monkeypatch):
    monkeypatch.delenv("KRONOS_ENABLED", raising=False)
    assert is_kronos_enabled() is True


def test_is_kronos_enabled_false_for_common_falsy(monkeypatch):
    for raw in ("0", "false", "False", "no", "off"):
        monkeypatch.setenv("KRONOS_ENABLED", raw)
        assert is_kronos_enabled() is False, raw


def test_run_kronos_skips_when_disabled(monkeypatch):
    monkeypatch.setenv("KRONOS_ENABLED", "false")

    with patch("rag_graphs.research_graph.nodes.run_kronos.get_yf_ticker") as mock_ticker:
        out = run_kronos({
            "ticker": "AAPL",
            "sections_markdown": {},
        })  # type: ignore[arg-type]

    mock_ticker.assert_not_called()
    assert out["kronos_data"]["available"] is False
    assert "disabled" in out["kronos_data"]["error"].lower()
    assert "disabled" in out["kronos_data"]["summary"].lower()
    assert "kronos" in out["sections_markdown"]
    assert "disabled" in out["sections_markdown"]["kronos"].lower()
    # Must not import / load the heavy forecaster path
    assert "KronosForecaster" not in out["sections_markdown"]["kronos"]


def test_run_kronos_still_runs_when_enabled(monkeypatch):
    monkeypatch.setenv("KRONOS_ENABLED", "true")

    with patch(
        "rag_graphs.research_graph.nodes.run_kronos.get_yf_ticker",
        side_effect=RuntimeError("boom"),
    ):
        out = run_kronos({
            "ticker": "AAPL",
            "sections_markdown": {},
        })  # type: ignore[arg-type]

    # Reached the yfinance path (not early-disabled)
    assert out["kronos_data"]["available"] is False
    assert "boom" in out["kronos_data"]["error"]
