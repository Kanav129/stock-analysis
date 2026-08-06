"""List-price estimates for Qwen / DashScope models (USD per 1M tokens)."""
from __future__ import annotations

from typing import TypedDict


class ModelRates(TypedDict):
    input: float
    output: float


# USD per 1M tokens — QwenCloud list prices (approx; PAYG invoices may differ slightly).
_MODEL_RATES: dict[str, ModelRates] = {
    "qwen3.7-flash": {"input": 0.03, "output": 0.13},
    "qwen3.7-plus": {"input": 0.40, "output": 1.60},
    "qwen3.7-max": {"input": 2.50, "output": 7.50},
    "qwen3.8-max": {"input": 2.00, "output": 6.00},
    "qwen3.5-flash": {"input": 0.065, "output": 0.26},
    "text-embedding-v4": {"input": 0.07, "output": 0.0},
}


def normalize_model_id(model: str) -> str:
    """Strip provider prefixes (e.g. qwen/qwen3.7-max → qwen3.7-max)."""
    name = (model or "").strip().lower()
    if "/" in name:
        name = name.rsplit("/", 1)[-1]
    return name


def lookup_rates(model: str) -> tuple[ModelRates | None, bool]:
    """Return (rates, known). known=False when model is not in the price table."""
    name = normalize_model_id(model)
    rates = _MODEL_RATES.get(name)
    if rates is not None:
        return rates, True
    # Prefix match for dated variants: qwen3.7-flash-2026-07-15
    for key, value in _MODEL_RATES.items():
        if name.startswith(key):
            return value, True
    return None, False


def estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int = 0,
) -> tuple[float, bool]:
    """Estimate USD cost from list prices.

    Returns (cost_usd, known_pricing).
    """
    rates, known = lookup_rates(model)
    if not known or rates is None:
        return 0.0, False
    inp = max(0, int(input_tokens or 0))
    out = max(0, int(output_tokens or 0))
    cost = (inp / 1_000_000.0) * rates["input"] + (out / 1_000_000.0) * rates["output"]
    return round(cost, 6), True
