"""Frozen score-first structured output for offline eval continuity."""
from __future__ import annotations

from pydantic import BaseModel, Field


class LegacyDecisionOutput(BaseModel):
    rating: str = Field(
        description=(
            "One of: STRONG_SELL, SELL, REDUCE, HOLD, ACCUMULATE, BUY, STRONG_BUY"
        )
    )
    score: int = Field(
        ge=-100,
        le=100,
        description="Overall AI score from -100 (strong sell) to +100 (strong buy)",
    )
    reasoning: str = Field(description="Full reasoning for the decision in markdown")
    key_drivers: list[str] = Field(description="Top 3-5 drivers of the rating")
    supporting_headlines: list[str] = Field(
        description="Relevant news headlines supporting the decision"
    )
    entry: float | None = Field(default=None, description="Suggested entry price level")
    stop: float | None = Field(default=None, description="Suggested stop-loss level")
    target: float | None = Field(default=None, description="Suggested target price")
    position_note: str = Field(
        default="Maintain current position.",
        description="Position sizing guidance",
    )
    posture: str = Field(
        default="",
        description="Brief posture statement for the decision brief",
    )
