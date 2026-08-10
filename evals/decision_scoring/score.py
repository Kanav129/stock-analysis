from __future__ import annotations

from typing import Any

from evals.decision_scoring.invoke_decision import InvokeResult
from evals.decision_scoring.street_map import (
    tag_within_tolerance,
    target_within_tolerance,
)

_BULLISH_RATINGS = {"ACCUMULATE", "BUY", "STRONG_BUY"}


def score_call(invoke: InvokeResult, gold: dict[str, Any]) -> dict[str, Any]:
    """Score one model invocation against optional street-consensus gold."""
    structure = invoke.structure
    structure_pass = invoke.call_ok and all(
        (
            structure.parsed_ok,
            structure.rating_ok,
            structure.score_ok,
            structure.reasoning_ok,
            structure.drivers_ok,
            structure.levels_types_ok,
        )
    )
    normalized = structure.normalized or {}
    rating = normalized.get("rating")
    score = normalized.get("score")
    target = normalized.get("target")

    recommendation_key = gold.get("recommendation_key")
    target_mean = gold.get("target_mean")
    tag_hit = None
    target_hit = None
    if structure_pass:
        if recommendation_key is not None:
            tag_hit = tag_within_tolerance(rating, recommendation_key)
        if target_mean is not None:
            target_hit = target_within_tolerance(target, target_mean)

    return {
        "structure_pass": structure_pass,
        "tag_hit": tag_hit,
        "target_hit": target_hit,
        "rating": rating,
        "score": score,
        "target": target,
        "schema_method": invoke.schema_method,
        "call_ok": invoke.call_ok,
        "latency_ms": invoke.latency_ms,
        "model": invoke.model,
        "raw_error": invoke.raw_error,
        "structure_errors": structure.errors,
    }


def aggregate_variant(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate metrics, gating quality metrics on passing structure."""
    passing = [row for row in rows if row.get("structure_pass") is True]
    gradable_tags = [row for row in passing if row.get("tag_hit") is not None]
    gradable_targets = [row for row in passing if row.get("target_hit") is not None]

    return {
        "structure_pass_rate": len(passing) / len(rows) if rows else 0.0,
        "tag_accuracy": (
            sum(row["tag_hit"] is True for row in gradable_tags) / len(gradable_tags)
            if gradable_tags
            else None
        ),
        "target_accuracy": (
            sum(row["target_hit"] is True for row in gradable_targets)
            / len(gradable_targets)
            if gradable_targets
            else None
        ),
        "distinct_scores": len(
            {row.get("score") for row in passing if row.get("score") is not None}
        ),
        "bullish_skew": (
            sum(row.get("rating") in _BULLISH_RATINGS for row in passing)
            / len(passing)
            if passing
            else None
        ),
    }
