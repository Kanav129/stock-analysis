"""Tests for LLM list-price estimates."""
from config.llm_pricing import estimate_cost_usd, normalize_model_id


def test_normalize_strips_provider_prefix():
    assert normalize_model_id("qwen/qwen3.7-max") == "qwen3.7-max"
    assert normalize_model_id("qwen3.7-flash") == "qwen3.7-flash"


def test_estimate_flash_cost():
    cost, known = estimate_cost_usd("qwen3.7-flash", 1_000_000, 1_000_000)
    assert known is True
    assert cost == round(0.03 + 0.13, 6)


def test_estimate_max_cost():
    cost, known = estimate_cost_usd("qwen3.7-max", 1_000_000, 0)
    assert known is True
    assert cost == 2.5


def test_unknown_model_zero_cost():
    cost, known = estimate_cost_usd("some-unknown-model", 10_000, 10_000)
    assert known is False
    assert cost == 0.0


def test_dated_variant_matches_prefix():
    cost, known = estimate_cost_usd("qwen3.7-flash-2026-07-15", 1_000_000, 0)
    assert known is True
    assert cost == 0.03
