from __future__ import annotations

import json
from typing import Any

from psycopg2.extras import Json

from config.rating_config import clamp_score, normalize_rating, score_from_legacy_confidence
from db.db_factory import get_db_client


def _extract_score(rating_obj: dict[str, Any]) -> int:
    if rating_obj.get("score") is not None:
        return clamp_score(rating_obj.get("score"))
    return score_from_legacy_confidence(
        str(rating_obj.get("rating") or "HOLD"),
        rating_obj.get("confidence"),
    )


class RatingsService:
    def get_latest_ratings(
        self, tickers: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Latest rating per ticker, preferring research-report ratings over analysis ratings."""
        ticker_filter: list[str] | None = None
        if tickers is not None:
            ticker_filter = sorted({str(t).upper() for t in tickers if t})
            if not ticker_filter:
                return []

        analysis = {
            r["ticker"]: r for r in self._latest_analysis_ratings(ticker_filter)
        }
        reports = {
            r["ticker"]: r for r in self._latest_report_ratings(ticker_filter)
        }

        universe = sorted(set(analysis) | set(reports))
        merged: list[dict[str, Any]] = []
        for ticker in universe:
            if ticker in reports:
                merged.append(reports[ticker])
            else:
                merged.append(analysis[ticker])
        return merged

    def _latest_analysis_ratings(
        self, tickers: list[str] | None = None
    ) -> list[dict[str, Any]]:
        db = get_db_client()
        if tickers:
            rows, cols = db.fetch_query(
                """
                SELECT DISTINCT ON (ticker)
                    id, ticker, rating, score, reasoning,
                    key_drivers, supporting_headlines, price_summary, model, created_at
                FROM stock_ratings
                WHERE ticker IN %s
                ORDER BY ticker, created_at DESC
                """,
                (tuple(tickers),),
            )
        else:
            rows, cols = db.fetch_query(
                """
                SELECT DISTINCT ON (ticker)
                    id, ticker, rating, score, reasoning,
                    key_drivers, supporting_headlines, price_summary, model, created_at
                FROM stock_ratings
                ORDER BY ticker, created_at DESC
                """
            )
        return [self._row_to_dict(cols, row) for row in rows]

    def _latest_report_ratings(
        self, tickers: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Map latest stock_reports.rating JSON into the StockRating shape.

        Extracts scalar fields in SQL so we don't ship full rating JSON blobs
        (reasoning can be large) across the wire for the desk list.
        """
        db = get_db_client()
        if tickers:
            rows, _ = db.fetch_query(
                """
                SELECT DISTINCT ON (ticker)
                    id,
                    ticker,
                    report_type,
                    rating->>'rating' AS rating_tag,
                    rating->>'score' AS score_raw,
                    rating->>'confidence' AS confidence_raw,
                    LEFT(COALESCE(rating->>'reasoning', ''), 280) AS reasoning,
                    rating->'key_drivers' AS key_drivers,
                    model,
                    created_at
                FROM stock_reports
                WHERE rating IS NOT NULL
                  AND rating->>'rating' IS NOT NULL
                  AND ticker IN %s
                ORDER BY ticker, created_at DESC
                """,
                (tuple(tickers),),
            )
        else:
            rows, _ = db.fetch_query(
                """
                SELECT DISTINCT ON (ticker)
                    id,
                    ticker,
                    report_type,
                    rating->>'rating' AS rating_tag,
                    rating->>'score' AS score_raw,
                    rating->>'confidence' AS confidence_raw,
                    LEFT(COALESCE(rating->>'reasoning', ''), 280) AS reasoning,
                    rating->'key_drivers' AS key_drivers,
                    model,
                    created_at
                FROM stock_reports
                WHERE rating IS NOT NULL
                  AND rating->>'rating' IS NOT NULL
                ORDER BY ticker, created_at DESC
                """
            )
        result: list[dict[str, Any]] = []
        for row in rows:
            (
                report_id,
                ticker,
                report_type,
                rating_tag,
                score_raw,
                confidence_raw,
                reasoning,
                key_drivers,
                model,
                created_at,
            ) = row
            if isinstance(key_drivers, str):
                try:
                    key_drivers = json.loads(key_drivers)
                except (json.JSONDecodeError, TypeError):
                    key_drivers = []
            score = None
            if score_raw is not None and score_raw != "":
                try:
                    score = clamp_score(int(float(score_raw)))
                except (TypeError, ValueError):
                    score = None
            if score is None:
                conf = None
                if confidence_raw is not None and confidence_raw != "":
                    try:
                        conf = int(float(confidence_raw))
                    except (TypeError, ValueError):
                        conf = None
                score = score_from_legacy_confidence(str(rating_tag or "HOLD"), conf)

            created = created_at.isoformat() if hasattr(created_at, "isoformat") else created_at
            result.append({
                "id": report_id,
                "ticker": ticker,
                "rating": normalize_rating(str(rating_tag or "HOLD")),
                "score": score,
                "reasoning": reasoning or "",
                "key_drivers": key_drivers or [],
                "supporting_headlines": [],
                "price_summary": {},
                "model": model,
                "created_at": created,
                "source": "report",
                "report_type": report_type,
            })
        return result

    def get_rating_history(self, ticker: str) -> list[dict[str, Any]]:
        ticker = ticker.upper()
        db = get_db_client()
        rows, cols = db.fetch_query(
            """
            SELECT id, ticker, rating, score, reasoning,
                   key_drivers, supporting_headlines, price_summary, model, created_at
            FROM stock_ratings
            WHERE ticker = %s
            ORDER BY created_at DESC
            """,
            (ticker,),
        )
        history = [self._row_to_dict(cols, row) for row in rows]

        report = next((r for r in self._latest_report_ratings() if r["ticker"] == ticker), None)
        if report:
            if not history or history[0].get("created_at") != report.get("created_at"):
                if not history or (report.get("created_at") or "") >= (history[0].get("created_at") or ""):
                    history = [report] + history
        return history

    def get_latest_for_ticker(self, ticker: str) -> dict[str, Any] | None:
        ticker = ticker.upper()
        for r in self._latest_report_ratings():
            if r["ticker"] == ticker:
                return r
        db = get_db_client()
        rows, cols = db.fetch_query(
            """
            SELECT id, ticker, rating, score, reasoning,
                   key_drivers, supporting_headlines, price_summary, model, created_at
            FROM stock_ratings
            WHERE ticker = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (ticker,),
        )
        if not rows:
            return None
        return self._row_to_dict(cols, rows[0])

    def save_rating(self, data: dict[str, Any]) -> None:
        score = data.get("score")
        if score is None and data.get("confidence") is not None:
            score = score_from_legacy_confidence(data.get("rating", "HOLD"), data.get("confidence"))
        score = clamp_score(score, 0)
        rating = normalize_rating(data.get("rating"))

        db = get_db_client()
        db.execute_query(
            """
            INSERT INTO stock_ratings
                (ticker, rating, score, reasoning, key_drivers, supporting_headlines, price_summary, model)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                data["ticker"].upper(),
                rating,
                score,
                data["reasoning"],
                Json(data.get("key_drivers", [])),
                Json(data.get("supporting_headlines", [])),
                Json(data.get("price_summary", {})),
                data.get("model"),
            ),
        )

    @staticmethod
    def _row_to_dict(cols: list[str], row: tuple) -> dict[str, Any]:
        result = dict(zip(cols, row))
        for key in ("key_drivers", "supporting_headlines", "price_summary"):
            val = result.get(key)
            if isinstance(val, str):
                result[key] = json.loads(val)
        if result.get("created_at"):
            result["created_at"] = result["created_at"].isoformat()
        if "score" in result:
            result["score"] = clamp_score(result.get("score"))
        result["rating"] = normalize_rating(result.get("rating"))
        result.setdefault("source", "analysis")
        return result
