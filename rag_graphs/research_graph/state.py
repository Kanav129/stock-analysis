"""Research graph state definition."""
from __future__ import annotations

from typing import Any, TypedDict


class ResearchState(TypedDict, total=False):
    # ── Inputs ──
    ticker: str
    report_type: str  # "core" or "deep"

    # ── Raw data (populated by gather nodes) ──
    market_data: dict[str, Any]
    fundamental_data: dict[str, Any]
    news_data: dict[str, Any]
    sentiment_data: dict[str, Any]

    # ── Deep-only sections ──
    flows_data: dict[str, Any]
    policy_data: dict[str, Any]
    lockup_data: dict[str, Any]
    kronos_data: dict[str, Any]
    debate_data: dict[str, Any]

    # ── Computed ──
    live_price: float
    factor_scores: dict[str, int]
    dimension_alignment: dict[str, Any]

    # ── Decision outputs ──
    rating: str
    score: int  # −100 (strong sell) … +100 (strong buy)
    reasoning: str
    key_drivers: list[str]
    supporting_headlines: list[dict[str, str]]
    entry_levels: dict[str, Any]
    posture: str
    calibration_note: str

    # ── Section markdown (for frontend rendering) ──
    sections_markdown: dict[str, str]

    # ── Metadata ──
    model: str
    errors: list[str]
    report_id: int