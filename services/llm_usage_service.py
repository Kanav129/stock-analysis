"""Record and aggregate local LLM usage (tokens + estimated USD)."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from config.llm_pricing import estimate_cost_usd
from db.db_factory import get_db_client
from services.run_checkpoint_service import app_timezone, day_bounds_utc, today_key
from utils.logger import logger

UsageRole = Literal["analysis", "research", "other"]
UsageRange = Literal["week", "month"]


def extract_token_usage(result: Any) -> tuple[int, int]:
    """Pull input/output token counts from a LangChain result or nested message."""
    if result is None:
        return 0, 0

    # Direct usage_metadata (AIMessage)
    usage = getattr(result, "usage_metadata", None)
    if isinstance(usage, dict):
        inp = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
        out = usage.get("output_tokens") or usage.get("completion_tokens") or 0
        if inp or out:
            return int(inp), int(out)

    # response_metadata.token_usage (ChatOpenAI)
    meta = getattr(result, "response_metadata", None)
    if isinstance(meta, dict):
        token_usage = meta.get("token_usage") or meta.get("usage") or {}
        if isinstance(token_usage, dict):
            inp = token_usage.get("prompt_tokens") or token_usage.get("input_tokens") or 0
            out = token_usage.get("completion_tokens") or token_usage.get("output_tokens") or 0
            if inp or out:
                return int(inp), int(out)

    # Structured output / Runnable result may wrap the message
    for attr in ("raw", "message", "generation", "ai_message"):
        nested = getattr(result, attr, None)
        if nested is not None and nested is not result:
            inp, out = extract_token_usage(nested)
            if inp or out:
                return inp, out

    # dict-shaped payloads
    if isinstance(result, dict):
        usage = result.get("usage_metadata") or result.get("token_usage") or result.get("usage")
        if isinstance(usage, dict):
            inp = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
            out = usage.get("output_tokens") or usage.get("completion_tokens") or 0
            if inp or out:
                return int(inp), int(out)
        for key in ("raw", "message", "response"):
            if key in result:
                inp, out = extract_token_usage(result[key])
                if inp or out:
                    return inp, out

    # Generations list (LLMResult-like)
    generations = getattr(result, "generations", None)
    if generations:
        try:
            first = generations[0][0] if generations[0] else None
            msg = getattr(first, "message", None) if first else None
            if msg is not None:
                return extract_token_usage(msg)
        except (IndexError, TypeError, AttributeError):
            pass

    return 0, 0


def _empty_bucket() -> dict[str, int | float]:
    return {
        "cost_usd": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }


def _bucket_from_row(
    cost: float,
    input_tokens: int,
    output_tokens: int,
) -> dict[str, int | float]:
    return {
        "cost_usd": round(float(cost), 6),
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "total_tokens": int(input_tokens) + int(output_tokens),
    }


def _add_into(target: dict[str, int | float], source: dict[str, int | float]) -> None:
    target["cost_usd"] = round(float(target["cost_usd"]) + float(source["cost_usd"]), 6)
    target["input_tokens"] = int(target["input_tokens"]) + int(source["input_tokens"])
    target["output_tokens"] = int(target["output_tokens"]) + int(source["output_tokens"])
    target["total_tokens"] = int(target["total_tokens"]) + int(source["total_tokens"])


class LlmUsageService:
    def record(
        self,
        *,
        role: UsageRole,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        result: Any = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        """Best-effort insert; never raises to callers."""
        try:
            if result is not None and not input_tokens and not output_tokens:
                input_tokens, output_tokens = extract_token_usage(result)
            input_tokens = max(0, int(input_tokens or 0))
            output_tokens = max(0, int(output_tokens or 0))
            cost, known = estimate_cost_usd(model, input_tokens, output_tokens)
            payload = dict(meta or {})
            if not known:
                payload["pricing_unknown"] = True
            db = get_db_client()
            db.execute_query(
                """
                INSERT INTO llm_usage (role, model, input_tokens, output_tokens, cost_usd, meta)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    role,
                    (model or "unknown").strip()[:128],
                    input_tokens,
                    output_tokens,
                    cost,
                    json.dumps(payload),
                ),
            )
        except Exception as exc:
            logger.warning(f"llm_usage record failed: {exc}")

    def record_from_result(
        self,
        *,
        role: UsageRole,
        model: str,
        result: Any,
        meta: dict[str, Any] | None = None,
    ) -> None:
        self.record(role=role, model=model, result=result, meta=meta)

    def get_usage_summary(self, range_: UsageRange = "week") -> dict[str, Any]:
        days = 7 if range_ == "week" else 30
        tz = app_timezone()
        today = today_key()
        y, m, d = (int(x) for x in today.split("-"))
        end_local = date(y, m, d)
        start_local = end_local - timedelta(days=days - 1)

        start_utc, _ = day_bounds_utc(start_local.isoformat())
        _, end_utc = day_bounds_utc(end_local.isoformat())

        # Period windows for tiles
        today_start, today_end = day_bounds_utc(today)
        week_start_day = (end_local - timedelta(days=6)).isoformat()
        month_start_day = (end_local - timedelta(days=29)).isoformat()
        week_start, _ = day_bounds_utc(week_start_day)
        month_start, _ = day_bounds_utc(month_start_day)

        rows = self._fetch_rows(month_start, today_end)

        periods = {
            "today": self._aggregate_period(rows, today_start, today_end),
            "week": self._aggregate_period(rows, week_start, today_end),
            "month": self._aggregate_period(rows, month_start, today_end),
        }

        # Daily series for chart range
        chart_start, _ = day_bounds_utc(start_local.isoformat())
        daily_map = self._daily_map(rows, chart_start, end_utc, tz)
        daily: list[dict[str, Any]] = []
        cursor = start_local
        while cursor <= end_local:
            key = cursor.isoformat()
            day_data = daily_map.get(key) or {
                "analysis": _empty_bucket(),
                "research": _empty_bucket(),
                "other": _empty_bucket(),
            }
            analysis = day_data["analysis"]
            research = day_data["research"]
            other = day_data["other"]
            total_cost = (
                float(analysis["cost_usd"])
                + float(research["cost_usd"])
                + float(other["cost_usd"])
            )
            total_tokens = (
                int(analysis["total_tokens"])
                + int(research["total_tokens"])
                + int(other["total_tokens"])
            )
            daily.append(
                {
                    "date": key,
                    "analysis_cost": float(analysis["cost_usd"]),
                    "research_cost": float(research["cost_usd"]),
                    "other_cost": float(other["cost_usd"]),
                    "total_cost": round(total_cost, 6),
                    "analysis_tokens": int(analysis["total_tokens"]),
                    "research_tokens": int(research["total_tokens"]),
                    "other_tokens": int(other["total_tokens"]),
                    "total_tokens": total_tokens,
                }
            )
            cursor += timedelta(days=1)

        return {
            "currency": "USD",
            "periods": periods,
            "daily": daily,
            "range": range_,
            "note": "Estimated from Qwen list prices; PAYG invoices may differ slightly.",
        }

    def _fetch_rows(
        self,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[tuple[Any, ...]]:
        db = get_db_client()
        try:
            rows, _ = db.fetch_query(
                """
                SELECT created_at, role, input_tokens, output_tokens, cost_usd
                FROM llm_usage
                WHERE created_at >= %s AND created_at < %s
                """,
                (start_utc, end_utc),
            )
            return list(rows or [])
        except Exception as exc:
            logger.warning(f"llm_usage fetch failed: {exc}")
            return []

    def _aggregate_period(
        self,
        rows: list[tuple[Any, ...]],
        start_utc: datetime,
        end_utc: datetime,
    ) -> dict[str, dict[str, int | float]]:
        analysis = _empty_bucket()
        research = _empty_bucket()
        other = _empty_bucket()
        for created_at, role, input_tokens, output_tokens, cost_usd in rows:
            ts = created_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < start_utc or ts >= end_utc:
                continue
            bucket = _bucket_from_row(float(cost_usd or 0), int(input_tokens or 0), int(output_tokens or 0))
            if role == "analysis":
                _add_into(analysis, bucket)
            elif role == "research":
                _add_into(research, bucket)
            else:
                _add_into(other, bucket)
        total = _empty_bucket()
        _add_into(total, analysis)
        _add_into(total, research)
        _add_into(total, other)
        return {
            "total": total,
            "analysis": analysis,
            "research": research,
            "other": other,
        }

    def _daily_map(
        self,
        rows: list[tuple[Any, ...]],
        start_utc: datetime,
        end_utc: datetime,
        tz,
    ) -> dict[str, dict[str, dict[str, int | float]]]:
        out: dict[str, dict[str, dict[str, int | float]]] = {}
        for created_at, role, input_tokens, output_tokens, cost_usd in rows:
            ts = created_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < start_utc or ts >= end_utc:
                continue
            day = ts.astimezone(tz).date().isoformat()
            if day not in out:
                out[day] = {
                    "analysis": _empty_bucket(),
                    "research": _empty_bucket(),
                    "other": _empty_bucket(),
                }
            role_key = role if role in ("analysis", "research", "other") else "other"
            bucket = _bucket_from_row(float(cost_usd or 0), int(input_tokens or 0), int(output_tokens or 0))
            _add_into(out[day][role_key], bucket)
        return out
