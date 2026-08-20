from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import ValidationError

from config.rating_config import RATING_SET, clamp_score, rating_from_score
from config.score_composite import composite_score
from evals.decision_scoring.legacy_output import LegacyDecisionOutput
from rag_graphs.research_graph.nodes.synthesize_decision import DecisionOutput

SchemaKind = Literal["score_first", "rubric"]


@dataclass
class StructureResult:
    parsed_ok: bool
    rating_ok: bool
    score_ok: bool
    reasoning_ok: bool
    drivers_ok: bool
    levels_types_ok: bool
    errors: list[str] = field(default_factory=list)
    normalized: dict | None = None


def _raw_rating_key(raw: Any) -> str | None:
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        return None
    key = str(raw).upper().replace(" ", "_").replace("-", "_")
    aliases = {
        "STRONGBUY": "STRONG_BUY",
        "STRONGSELL": "STRONG_SELL",
        "UNDERWEIGHT": "REDUCE",
        "OVERWEIGHT": "ACCUMULATE",
        "NEUTRAL": "HOLD",
    }
    return aliases.get(key, key)


def _rating_is_valid(raw: Any) -> bool:
    key = _raw_rating_key(raw)
    return key is not None and key in RATING_SET


def _score_in_range(raw: Any) -> bool:
    if raw is None:
        return False
    try:
        score = int(raw)
    except (TypeError, ValueError):
        return False
    return -100 <= score <= 100


def _reasoning_is_valid(raw: Any) -> bool:
    return isinstance(raw, str) and bool(raw.strip())


def _drivers_are_valid(raw: Any) -> bool:
    return (
        isinstance(raw, list)
        and len(raw) > 0
        and all(isinstance(item, str) for item in raw)
    )


def _levels_types_are_valid(obj: dict[str, Any]) -> bool:
    for key in ("entry", "stop", "target"):
        value = obj.get(key)
        if value is not None and not isinstance(value, (int, float)):
            return False
    return True


def validate_decision_payload(
    obj: Any,
    *,
    schema: SchemaKind = "rubric",
) -> StructureResult:
    if not isinstance(obj, dict):
        return StructureResult(
            parsed_ok=False,
            rating_ok=False,
            score_ok=False,
            reasoning_ok=False,
            drivers_ok=False,
            levels_types_ok=False,
            errors=["payload must be a dict"],
            normalized=None,
        )

    reasoning_ok = _reasoning_is_valid(obj.get("reasoning"))
    drivers_ok = _drivers_are_valid(obj.get("key_drivers"))
    levels_types_ok = _levels_types_are_valid(obj)
    model_cls = DecisionOutput if schema == "rubric" else LegacyDecisionOutput

    normalized: dict | None = None
    parsed_ok = False
    errors: list[str] = []
    try:
        model = model_cls.model_validate(obj)
        parsed_ok = True
        normalized = model.model_dump()
    except ValidationError as exc:
        errors.extend(
            f"{'.'.join(str(part) for part in err.get('loc', ()))}: {err.get('msg', 'invalid')}"
            for err in exc.errors()
        )

    if schema == "rubric" and parsed_ok and normalized is not None:
        score, _note = composite_score(normalized)
        rating = rating_from_score(score)
        normalized["score"] = score
        normalized["rating"] = rating
        score_ok = _score_in_range(score)
        rating_ok = _rating_is_valid(rating)
    else:
        score_ok = _score_in_range(obj.get("score"))
        rating_ok = _rating_is_valid(obj.get("rating"))
        if parsed_ok and normalized is not None and normalized.get("score") is not None:
            try:
                normalized["rating"] = rating_from_score(
                    clamp_score(normalized.get("score"))
                )
            except Exception:
                pass

    return StructureResult(
        parsed_ok=parsed_ok,
        rating_ok=rating_ok,
        score_ok=score_ok,
        reasoning_ok=reasoning_ok,
        drivers_ok=drivers_ok,
        levels_types_ok=levels_types_ok,
        errors=errors,
        normalized=normalized,
    )
