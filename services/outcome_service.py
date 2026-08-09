"""Materialize forward price outcomes (+5d / +20d) for historical ratings."""
from __future__ import annotations

import json
import statistics
from datetime import date, datetime, timezone
from typing import Any, Sequence

from config.rating_config import RATING_SCORE_BANDS, normalize_rating
from db.db_factory import get_db_client
from utils.logger import logger

BULLISH = frozenset({"ACCUMULATE", "BUY", "STRONG_BUY"})
BEARISH = frozenset({"REDUCE", "SELL", "STRONG_SELL"})
MIN_SLICE_N = 10


def extract_entry_price(price_summary: Any, report_live_price: Any = None) -> float | None:
    """Resolve entry price from rating price_summary or nearest report live_price."""
    summary = price_summary
    if isinstance(summary, str):
        try:
            summary = json.loads(summary)
        except (TypeError, ValueError, json.JSONDecodeError):
            summary = None
    if isinstance(summary, dict):
        raw = summary.get("live_price")
        if raw is not None:
            try:
                price = float(raw)
                if price > 0:
                    return price
            except (TypeError, ValueError):
                pass
    if report_live_price is not None:
        try:
            price = float(report_live_price)
            if price > 0:
                return price
        except (TypeError, ValueError):
            pass
    return None


def compute_return(entry_price: float, exit_price: float) -> float:
    return (exit_price - entry_price) / entry_price


def direction_hit(rating: str | None, ret: float | None) -> bool | None:
    """Whether return moved in the rating's direction. HOLD → None."""
    if ret is None or rating is None:
        return None
    tag = normalize_rating(rating)
    if tag == "HOLD":
        return None
    if tag in BULLISH:
        return ret > 0
    if tag in BEARISH:
        return ret < 0
    return None


def forward_close(
    closes: Sequence[tuple[datetime, float]],
    rated_at: datetime,
    trading_days: int,
) -> tuple[float, datetime] | None:
    """Nth trading-day close on/after the rating calendar day.

    ``closes`` must be sorted ascending by bar timestamp. Daily bars are often
    stamped at midnight, so comparison uses dates: day 1 = first bar whose
    calendar date is >= rated_at's date; day N = that index + (N - 1).
    """
    if trading_days < 1 or not closes:
        return None
    rated = rated_at if rated_at.tzinfo else rated_at.replace(tzinfo=timezone.utc)
    rated_day = rated.date()
    start_idx = None
    for i, (ts, _close) in enumerate(closes):
        ts_aware = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        if ts_aware.date() >= rated_day:
            start_idx = i
            break
    if start_idx is None:
        return None
    target = start_idx + trading_days - 1
    if target >= len(closes):
        return None
    ts, close = closes[target]
    return float(close), ts


def outcome_status(
    *,
    entry_price: float | None,
    ready_5d: bool,
    ready_20d: bool,
) -> str:
    if entry_price is None:
        return "skipped"
    if ready_5d and ready_20d:
        return "complete"
    if ready_5d or ready_20d:
        return "partial"
    return "pending"


def score_band_key(score: int | None) -> str | None:
    """Map a score onto the configured guidance band label."""
    if score is None:
        return None
    # Prefer the band whose midpoint is closest when boundaries overlap.
    best: tuple[str, int] | None = None
    for _tag, (lo, hi) in RATING_SCORE_BANDS.items():
        if lo <= score <= hi:
            mid = (lo + hi) // 2
            dist = abs(score - mid)
            key = f"score_band={lo}_{hi}"
            if best is None or dist < best[1]:
                best = (key, dist)
    return best[0] if best else None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


class OutcomeService:
    def __init__(self) -> None:
        self._db = get_db_client()

    def refresh(self, *, limit: int | None = None) -> dict[str, Any]:
        """Upsert outcomes for successful ratings and refresh calibration snapshots."""
        ratings = self._load_candidate_ratings(limit=limit)
        updated = 0
        skipped = 0
        for row in ratings:
            try:
                if self._upsert_outcome(row):
                    updated += 1
                else:
                    skipped += 1
            except Exception as exc:
                logger.warning(
                    "Outcome upsert failed for rating_id=%s: %s",
                    row.get("id"),
                    exc,
                )
                skipped += 1
        snap_count = 0
        try:
            snap_count = self.refresh_calibration_snapshots()
        except Exception as exc:
            logger.warning("Calibration snapshot refresh failed: %s", exc)
        logger.info(
            "Outcome refresh: candidates=%s updated=%s skipped=%s snapshots=%s",
            len(ratings),
            updated,
            skipped,
            snap_count,
        )
        return {
            "candidates": len(ratings),
            "updated": updated,
            "skipped": skipped,
            "snapshots": snap_count,
        }

    def _load_candidate_ratings(self, *, limit: int | None) -> list[dict[str, Any]]:
        sql = """
            SELECT r.id, r.ticker, r.rating, r.score, r.report_type,
                   r.price_summary, r.created_at,
                   (
                     SELECT sr.live_price
                     FROM stock_reports sr
                     WHERE sr.ticker = r.ticker
                       AND (r.report_type IS NULL OR sr.report_type = r.report_type)
                       AND sr.created_at <= r.created_at + INTERVAL '1 day'
                       AND sr.created_at >= r.created_at - INTERVAL '1 day'
                     ORDER BY ABS(EXTRACT(EPOCH FROM (sr.created_at - r.created_at)))
                     LIMIT 1
                   ) AS report_live_price
            FROM stock_ratings r
            WHERE r.decision_ok IS TRUE
              AND r.rating IS NOT NULL
              AND r.score IS NOT NULL
            ORDER BY r.created_at ASC
        """
        params: tuple[Any, ...] = ()
        if limit is not None:
            sql += " LIMIT %s"
            params = (int(limit),)
        rows, cols = self._db.fetch_query(sql, params)
        results: list[dict[str, Any]] = []
        for row in rows or []:
            results.append(dict(zip(cols, row)))
        return results

    def _load_daily_closes(
        self, ticker: str, rated_at: datetime
    ) -> list[tuple[datetime, float]]:
        rows, _ = self._db.fetch_query(
            """
            SELECT bar_ts, close
            FROM stock_data
            WHERE ticker = %s
              AND bar_interval = '1d'
              AND close IS NOT NULL
              AND bar_ts >= %s::timestamptz - INTERVAL '5 days'
            ORDER BY bar_ts ASC
            """,
            (ticker.upper(), rated_at),
        )
        out: list[tuple[datetime, float]] = []
        for ts, close in rows or []:
            try:
                out.append((ts, float(close)))
            except (TypeError, ValueError):
                continue
        return out

    def _upsert_outcome(self, row: dict[str, Any]) -> bool:
        rating_id = int(row["id"])
        ticker = str(row["ticker"]).upper()
        rated_at = row["created_at"]
        if isinstance(rated_at, str):
            rated_at = datetime.fromisoformat(rated_at.replace("Z", "+00:00"))
        entry = extract_entry_price(row.get("price_summary"), row.get("report_live_price"))
        rating = row.get("rating")
        score = row.get("score")
        report_type = row.get("report_type")

        price_5d = return_5d = ready_5d_at = None
        price_20d = return_20d = ready_20d_at = None
        hit_5d = hit_20d = None

        if entry is not None:
            closes = self._load_daily_closes(ticker, rated_at)
            fwd5 = forward_close(closes, rated_at, 5)
            if fwd5:
                price_5d, ready_5d_at = fwd5
                return_5d = compute_return(entry, price_5d)
                hit_5d = direction_hit(rating, return_5d)
            fwd20 = forward_close(closes, rated_at, 20)
            if fwd20:
                price_20d, ready_20d_at = fwd20
                return_20d = compute_return(entry, price_20d)
                hit_20d = direction_hit(rating, return_20d)

        status = outcome_status(
            entry_price=entry,
            ready_5d=price_5d is not None,
            ready_20d=price_20d is not None,
        )

        self._db.execute_query(
            """
            INSERT INTO rating_outcomes (
                rating_id, ticker, rated_at, rating, score, report_type,
                entry_price, price_5d, return_5d, ready_5d_at,
                price_20d, return_20d, ready_20d_at,
                direction_hit_5d, direction_hit_20d, status, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, NOW()
            )
            ON CONFLICT (rating_id) DO UPDATE SET
                ticker = EXCLUDED.ticker,
                rated_at = EXCLUDED.rated_at,
                rating = EXCLUDED.rating,
                score = EXCLUDED.score,
                report_type = EXCLUDED.report_type,
                entry_price = EXCLUDED.entry_price,
                price_5d = EXCLUDED.price_5d,
                return_5d = EXCLUDED.return_5d,
                ready_5d_at = EXCLUDED.ready_5d_at,
                price_20d = EXCLUDED.price_20d,
                return_20d = EXCLUDED.return_20d,
                ready_20d_at = EXCLUDED.ready_20d_at,
                direction_hit_5d = EXCLUDED.direction_hit_5d,
                direction_hit_20d = EXCLUDED.direction_hit_20d,
                status = EXCLUDED.status,
                updated_at = NOW()
            """,
            (
                rating_id,
                ticker,
                rated_at,
                rating,
                score,
                report_type,
                entry,
                price_5d,
                return_5d,
                ready_5d_at,
                price_20d,
                return_20d,
                ready_20d_at,
                hit_5d,
                hit_20d,
                status,
            ),
        )
        return True

    def refresh_calibration_snapshots(self, *, as_of: date | None = None) -> int:
        """Rebuild today's calibration snapshots from completed/partial outcomes."""
        day = as_of or datetime.now(timezone.utc).date()
        rows, _ = self._db.fetch_query(
            """
            SELECT rating, score, report_type, return_5d, return_20d,
                   direction_hit_5d, direction_hit_20d, status
            FROM rating_outcomes
            WHERE status IN ('partial', 'complete')
            """
        )
        buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in rows or []:
            rating, score, report_type, r5, r20, h5, h20, status = row
            base_keys: list[str] = []
            if rating:
                base_keys.append(f"rating={normalize_rating(rating)}")
            band = score_band_key(int(score) if score is not None else None)
            if band:
                base_keys.append(band)
            if report_type:
                base_keys.append(f"report_type={report_type}")
            for key in base_keys:
                for horizon, ret, hit, ready in (
                    ("5d", r5, h5, r5 is not None),
                    ("20d", r20, h20, r20 is not None),
                ):
                    if not ready:
                        continue
                    buckets.setdefault((horizon, key), []).append(
                        {"return": float(ret), "hit": hit}
                    )

        # Replace today's snapshots for idempotency
        self._db.execute_query(
            "DELETE FROM analysis_calibration_snapshots WHERE as_of = %s",
            (day,),
        )
        count = 0
        for (horizon, slice_key), items in buckets.items():
            n = len(items)
            returns = [i["return"] for i in items]
            hits = [i["hit"] for i in items if i["hit"] is not None]
            hit_rate = (sum(1 for h in hits if h) / len(hits)) if hits else None
            avg_ret = (sum(returns) / len(returns)) if returns else None
            med_ret = _median(returns)
            notes = None
            if n < MIN_SLICE_N:
                notes = f"thin sample (n={n}; min={MIN_SLICE_N})"
            self._db.execute_query(
                """
                INSERT INTO analysis_calibration_snapshots (
                    as_of, horizon, slice_key, n, hit_rate,
                    avg_return, median_return, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (day, horizon, slice_key, n, hit_rate, avg_ret, med_ret, notes),
            )
            count += 1
        return count


outcome_service = OutcomeService()
