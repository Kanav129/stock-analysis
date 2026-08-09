"""Build historical performance priors for deep analysis decisions."""
from __future__ import annotations

import json
from typing import Any

from db.db_factory import get_db_client
from services.outcome_service import MIN_SLICE_N, score_band_key
from utils.logger import logger

MAX_PRIORS_CHARS = 2000
SAME_TICKER_LIMIT = 4
SIMILAR_CASE_LIMIT = 5
SCORE_WINDOW = 15
FACTOR_KEYS = ("value", "growth", "quality", "momentum", "low_risk", "sentiment")


def _parse_jsonish(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return value
    return value


def _drivers_list(raw: Any) -> list[str]:
    data = _parse_jsonish(raw) or []
    if not isinstance(data, list):
        return []
    out: list[str] = []
    for item in data:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict):
            text = item.get("driver") or item.get("text") or item.get("headline")
            if text:
                out.append(str(text).strip())
    return out


def _factor_dict(raw: Any) -> dict[str, float]:
    data = _parse_jsonish(raw) or {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, float] = {}
    for key in FACTOR_KEYS:
        if key in data and data[key] is not None:
            try:
                out[key] = float(data[key])
            except (TypeError, ValueError):
                continue
    return out


def factor_distance(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 999.0
    diffs = []
    for key in FACTOR_KEYS:
        if key in a and key in b:
            diffs.append(abs(a[key] - b[key]))
    if not diffs:
        return 999.0
    return sum(diffs) / len(diffs)


def driver_overlap(a: list[str], b: list[str]) -> int:
    if not a or not b:
        return 0
    sa = {x.lower() for x in a}
    sb = {x.lower() for x in b}
    # Token overlap on short phrases
    ta = {t for s in sa for t in s.split() if len(t) > 3}
    tb = {t for s in sb for t in s.split() if len(t) > 3}
    return len(sa & sb) + len(ta & tb)


def _fmt_pct(ret: float | None) -> str:
    if ret is None:
        return "n/a"
    return f"{ret * 100:+.1f}%"


def _fmt_hit(hit: bool | None) -> str:
    if hit is None:
        return "n/a"
    return "hit" if hit else "miss"


def format_case_line(case: dict[str, Any]) -> str:
    rated = case.get("rated_at")
    rated_s = str(rated)[:10] if rated else "?"
    return (
        f"- {case.get('ticker')} {rated_s}: {case.get('rating')} "
        f"{int(case['score']):+d} → 5d {_fmt_pct(case.get('return_5d'))} "
        f"({_fmt_hit(case.get('direction_hit_5d'))}), "
        f"20d {_fmt_pct(case.get('return_20d'))} "
        f"({_fmt_hit(case.get('direction_hit_20d'))})"
    )


def build_priors_markdown(
    *,
    same_ticker: list[dict[str, Any]],
    similar: list[dict[str, Any]],
    aggregates: list[dict[str, Any]],
    max_chars: int = MAX_PRIORS_CHARS,
) -> str:
    """Compose the Historical performance priors block (bounded)."""
    lines = ["## Historical performance priors"]
    has_signal = bool(same_ticker or similar or aggregates)

    if not has_signal:
        lines.append(
            "- Insufficient history: no completed +5d/+20d outcomes yet. "
            "Score from current research only."
        )
        return "\n".join(lines)

    if same_ticker:
        lines.append("### Same ticker")
        for case in same_ticker[:SAME_TICKER_LIMIT]:
            lines.append(format_case_line(case))

    if similar:
        lines.append("### Similar cases")
        for case in similar[:SIMILAR_CASE_LIMIT]:
            lines.append(format_case_line(case))

    usable_aggs = [
        a for a in aggregates if int(a.get("n") or 0) >= MIN_SLICE_N
    ]
    thin_aggs = [a for a in aggregates if int(a.get("n") or 0) < MIN_SLICE_N]
    if usable_aggs:
        lines.append("### Aggregate calibration")
        for agg in usable_aggs:
            hit = agg.get("hit_rate")
            hit_s = f"{hit * 100:.0f}%" if hit is not None else "n/a"
            lines.append(
                f"- {agg.get('horizon')} {agg.get('slice_key')}: "
                f"n={agg.get('n')}, hit_rate={hit_s}, "
                f"avg={_fmt_pct(agg.get('avg_return'))}, "
                f"median={_fmt_pct(agg.get('median_return'))}"
            )
    elif thin_aggs or has_signal:
        lines.append(
            "- Aggregate slices still thin "
            f"(need n≥{MIN_SLICE_N}); treat case history cautiously."
        )

    lines.append(
        "_Use these priors to calibrate conviction only. "
        "Current research dominates; if priors conflict, say so in reasoning._"
    )

    text = "\n".join(lines)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


class AnalysisKnowledgeService:
    def __init__(self) -> None:
        self._db = get_db_client()

    def priors_for_deep(
        self,
        ticker: str,
        *,
        score: int | None = None,
        factor_scores: dict[str, Any] | None = None,
        key_drivers: list[str] | None = None,
    ) -> str:
        """Return markdown priors for a deep analysis of ``ticker``."""
        try:
            same = self._same_ticker_cases(ticker)
            similar = self._similar_cases(
                ticker,
                score=score,
                factor_scores=_factor_dict(factor_scores),
                key_drivers=key_drivers or [],
            )
            aggregates = self._aggregate_slices(score=score)
            return build_priors_markdown(
                same_ticker=same,
                similar=similar,
                aggregates=aggregates,
            )
        except Exception as exc:
            logger.warning("Knowledge priors failed for %s: %s", ticker, exc)
            return (
                "## Historical performance priors\n"
                "- Priors unavailable (lookup failed). "
                "Score from current research only."
            )

    def _same_ticker_cases(self, ticker: str) -> list[dict[str, Any]]:
        rows, cols = self._db.fetch_query(
            """
            SELECT o.ticker, o.rated_at, o.rating, o.score,
                   o.return_5d, o.return_20d,
                   o.direction_hit_5d, o.direction_hit_20d, o.status
            FROM rating_outcomes o
            WHERE o.ticker = %s
              AND o.status IN ('partial', 'complete')
              AND (o.return_5d IS NOT NULL OR o.return_20d IS NOT NULL)
            ORDER BY o.rated_at DESC
            LIMIT %s
            """,
            (ticker.upper(), SAME_TICKER_LIMIT),
        )
        return [dict(zip(cols, row)) for row in rows or []]

    def _similar_cases(
        self,
        ticker: str,
        *,
        score: int | None,
        factor_scores: dict[str, float],
        key_drivers: list[str],
    ) -> list[dict[str, Any]]:
        params: list[Any] = [ticker.upper()]
        score_clause = ""
        if score is not None:
            score_clause = "AND o.score BETWEEN %s AND %s"
            params.extend([score - SCORE_WINDOW, score + SCORE_WINDOW])
        params.append(40)  # fetch pool before ranking
        rows, cols = self._db.fetch_query(
            f"""
            SELECT o.ticker, o.rated_at, o.rating, o.score, o.report_type,
                   o.return_5d, o.return_20d,
                   o.direction_hit_5d, o.direction_hit_20d,
                   r.key_drivers,
                   (
                     SELECT sr.factor_scores
                     FROM stock_reports sr
                     WHERE sr.ticker = o.ticker
                       AND (o.report_type IS NULL OR sr.report_type = o.report_type)
                       AND sr.created_at <= o.rated_at + INTERVAL '1 day'
                       AND sr.created_at >= o.rated_at - INTERVAL '1 day'
                     ORDER BY ABS(EXTRACT(EPOCH FROM (sr.created_at - o.rated_at)))
                     LIMIT 1
                   ) AS factor_scores
            FROM rating_outcomes o
            JOIN stock_ratings r ON r.id = o.rating_id
            WHERE o.ticker <> %s
              AND o.status IN ('partial', 'complete')
              AND (o.return_5d IS NOT NULL OR o.return_20d IS NOT NULL)
              {score_clause}
            ORDER BY o.rated_at DESC
            LIMIT %s
            """,
            tuple(params),
        )
        cases = [dict(zip(cols, row)) for row in rows or []]
        ranked: list[tuple[float, dict[str, Any]]] = []
        for case in cases:
            dist = factor_distance(factor_scores, _factor_dict(case.get("factor_scores")))
            overlap = driver_overlap(key_drivers, _drivers_list(case.get("key_drivers")))
            # Lower score is better; prefer closer factors and more driver overlap
            rank = dist - (overlap * 5.0)
            if score is not None and case.get("score") is not None:
                rank += abs(int(case["score"]) - score) / 50.0
            ranked.append((rank, case))
        ranked.sort(key=lambda x: x[0])
        return [c for _, c in ranked[:SIMILAR_CASE_LIMIT]]

    def _aggregate_slices(self, *, score: int | None) -> list[dict[str, Any]]:
        keys: list[str] = []
        band = score_band_key(score)
        if band:
            keys.append(band)
        if score is not None:
            # Also pull rating-band aggregates near the implied tag from score sign
            if score >= 40:
                keys.append("rating=BUY")
            elif score <= -40:
                keys.append("rating=SELL")
            elif score >= 15:
                keys.append("rating=ACCUMULATE")
            elif score <= -15:
                keys.append("rating=REDUCE")
            else:
                keys.append("rating=HOLD")
        keys.append("report_type=deep")
        if not keys:
            return []
        rows, cols = self._db.fetch_query(
            """
            SELECT DISTINCT ON (horizon, slice_key)
                   as_of, horizon, slice_key, n, hit_rate,
                   avg_return, median_return, notes
            FROM analysis_calibration_snapshots
            WHERE slice_key = ANY(%s)
            ORDER BY horizon, slice_key, as_of DESC
            """,
            (keys,),
        )
        return [dict(zip(cols, row)) for row in rows or []]


analysis_knowledge_service = AnalysisKnowledgeService()
