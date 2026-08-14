"""Research graph state definition."""
from __future__ import annotations

from typing import Annotated, Any, TypedDict


def merge_dicts(left: dict | None, right: dict | None) -> dict:
    """LangGraph reducer so parallel gather nodes can each add section keys."""
    if not left:
        return dict(right or {})
    if not right:
        return dict(left)
    return {**left, **right}


class ResearchState(TypedDict, total=False):
    # ── Inputs ──
    ticker: str
    report_type: str  # "core" or "deep"

    # ── Raw data (populated by gather nodes) ──
    market_data: dict[str, Any]
    fundamental_data: dict[str, Any]
    news_data: dict[str, Any]
    sentiment_data: dict[str, Any]
    catalysts_data: dict[str, Any]

    # ── Deep-only sections ──
    flows_data: dict[str, Any]
    policy_data: dict[str, Any]
    lockup_data: dict[str, Any]
    kronos_data: dict[str, Any]
    debate_data: dict[str, Any]

    # ── Computed ──
    live_price: float
    factor_scores: dict[str, Any]
    dimension_alignment: dict[str, Any]

    # ── Decision outputs ──
    decision_ok: bool
    error_message: str | None
    rating: str | None
    score: int | None  # −100 (strong sell) … +100 (strong buy)
    reasoning: str
    key_drivers: list[str]
    supporting_headlines: list[dict[str, str]]
    entry_levels: dict[str, Any]
    posture: str
    calibration_note: str

    # ── Section markdown (for frontend rendering) ──
    sections_markdown: Annotated[dict[str, str], merge_dicts]

    # ── Metadata ──
    model: str
    errors: list[str]
    report_id: int
