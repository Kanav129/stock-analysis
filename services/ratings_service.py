from __future__ import annotations

import json
from typing import Any

from psycopg2.extras import Json

from config.rating_config import clamp_score, normalize_rating, score_from_legacy_confidence
from db.db_factory import get_db_client

RATING_SELECT = """
    id, ticker, rating, score, reasoning,
    key_drivers, supporting_headlines, price_summary, model, report_type,
    decision_ok, error_message, created_at
"""


def _extract_score(rating_obj: dict[str, Any]) -> int:
    if rating_obj.get("score") is not None:
        return clamp_score(rating_obj.get("score"))
    return score_from_legacy_confidence(
        str(rating_obj.get("rating") or "HOLD"),
        rating_obj.get("confidence"),
    )


def _normalize_report_type(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip().lower()
    if raw in {"core", "deep"}:
        return raw
    return None


def merge_success_and_failure(
    success: dict[str, Any] | None,
    failure: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return the last successful decision, annotated by a newer failure."""
    if success is None and failure is None:
        return None
    if failure is None:
        return dict(success) if success is not None else None

    failure_is_latest = (
        success is None
        or (failure.get("created_at") or "") > (success.get("created_at") or "")
    )
    if not failure_is_latest:
        return dict(success) if success is not None else None

    result = dict(success) if success is not None else dict(failure)
    if success is None:
        result["rating"] = None
        result["score"] = None
    result["analysis_failed"] = True
    result["analysis_error"] = failure.get("error_message")
    result["failed_at"] = failure.get("created_at")
    return result


def _merge_rating_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge the latest successful and failed rows for each ticker."""
    successes: dict[str, dict[str, Any]] = {}
    failures: dict[str, dict[str, Any]] = {}
    for row in rows:
        target = successes if row.get("decision_ok", True) else failures
        ticker = row["ticker"]
        current = target.get(ticker)
        if current is None or (row.get("created_at") or "") > (
            current.get("created_at") or ""
        ):
            target[ticker] = row

    return [
        merged
        for ticker in sorted(set(successes) | set(failures))
        if (merged := merge_success_and_failure(
            successes.get(ticker), failures.get(ticker)
        )) is not None
    ]


def _failure_from_display(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row or not row.get("analysis_failed"):
        return None
    failure = dict(row)
    failure["created_at"] = row.get("failed_at")
    failure["error_message"] = row.get("analysis_error")
    failure["decision_ok"] = False
    failure["rating"] = None
    failure["score"] = None
    return failure


class RatingsService:
    def list_latest_failures(self) -> list[dict[str, str]]:
        """Latest failed attempt per ticker, preserving report type (core|deep)."""
        db = get_db_client()
        rows, _ = db.fetch_query(
            """
            WITH attempts AS (
                SELECT
                    ticker,
                    CASE
                        WHEN lower(coalesce(report_type, '')) = 'deep' THEN 'deep'
                        ELSE 'core'
                    END AS report_type,
                    COALESCE(decision_ok, TRUE) AS decision_ok,
                    created_at
                FROM stock_ratings

                UNION ALL

                SELECT
                    ticker,
                    CASE
                        WHEN lower(coalesce(report_type, '')) = 'deep' THEN 'deep'
                        ELSE 'core'
                    END AS report_type,
                    (rating->>'decision_ok') IS DISTINCT FROM 'false' AS decision_ok,
                    created_at
                FROM stock_reports
                WHERE rating IS NOT NULL
                  AND (
                      (rating->>'decision_ok') = 'false'
                      OR rating->>'rating' IS NOT NULL
                  )
            ),
            latest AS (
                SELECT DISTINCT ON (ticker)
                    ticker,
                    report_type,
                    decision_ok
                FROM attempts
                ORDER BY ticker, created_at DESC, decision_ok ASC
            )
            SELECT ticker, report_type
            FROM latest
            WHERE decision_ok = FALSE
            ORDER BY ticker
            """
        )
        return [
            {
                "ticker": str(row[0]).upper(),
                "report_type": "deep" if str(row[1]).lower() == "deep" else "core",
            }
            for row in rows
        ]

    def list_tickers_with_latest_failure(self) -> list[str]:
        """Tickers whose latest rating attempt across ratings and reports failed."""
        return [item["ticker"] for item in self.list_latest_failures()]

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
            report = reports.get(ticker)
            analysis_row = analysis.get(ticker)
            success = (
                report if report and report.get("rating") is not None
                else analysis_row if analysis_row and analysis_row.get("rating") is not None
                else None
            )
            failures = [
                failure
                for failure in (
                    _failure_from_display(report),
                    _failure_from_display(analysis_row),
                )
                if failure is not None
            ]
            failure = max(
                failures,
                key=lambda item: item.get("created_at") or "",
                default=None,
            )
            if success is not None:
                success = dict(success)
                for key in ("analysis_failed", "analysis_error", "failed_at"):
                    success.pop(key, None)
            display = merge_success_and_failure(success, failure)
            if display is not None:
                merged.append(display)
        return merged

    def get_recent_ratings(self, limit: int = 8, *, days: int = 5) -> list[dict[str, Any]]:
        """Latest rating per ticker from the last ``days`` (newest first)."""
        n = max(1, min(int(limit), 50))
        window_days = max(1, min(int(days), 90))
        db = get_db_client()
        # Select tickers with a recent attempt, then retrieve their last success
        # and failure (the displayed success can predate the recent window).
        rows, cols = db.fetch_query(
            f"""
            WITH candidate_tickers AS (
                SELECT ticker
                FROM (
                    SELECT DISTINCT ON (ticker) ticker, created_at
                    FROM stock_ratings
                    WHERE created_at >= NOW() - (%s * INTERVAL '1 day')
                    ORDER BY ticker, created_at DESC
                ) latest
                ORDER BY created_at DESC
                LIMIT %s
            ),
            ranked AS (
                SELECT DISTINCT ON (sr.ticker, COALESCE(sr.decision_ok, TRUE))
                    sr.id, sr.ticker, sr.rating, sr.score,
                    LEFT(COALESCE(sr.reasoning, ''), 280) AS reasoning,
                    sr.key_drivers, sr.supporting_headlines, sr.price_summary,
                    sr.model, sr.report_type, sr.decision_ok,
                    sr.error_message, sr.created_at
                FROM stock_ratings sr
                JOIN candidate_tickers candidates ON candidates.ticker = sr.ticker
                ORDER BY sr.ticker, COALESCE(sr.decision_ok, TRUE), sr.created_at DESC
            )
            SELECT * FROM ranked
            """,
            (window_days, n),
        )
        merged = _merge_rating_rows([self._row_to_dict(cols, row) for row in rows])
        merged.sort(
            key=lambda item: item.get("failed_at") or item.get("created_at") or "",
            reverse=True,
        )
        return merged[:n]

    def _latest_analysis_ratings(
        self, tickers: list[str] | None = None
    ) -> list[dict[str, Any]]:
        db = get_db_client()
        ticker_clause = "WHERE ticker IN %s" if tickers else ""
        params = (tuple(tickers),) if tickers else None
        query = f"""
            SELECT DISTINCT ON (ticker, COALESCE(decision_ok, TRUE))
                {RATING_SELECT}
            FROM stock_ratings
            {ticker_clause}
            ORDER BY ticker, COALESCE(decision_ok, TRUE), created_at DESC
        """
        if tickers:
            rows, cols = db.fetch_query(query, params)
        else:
            rows, cols = db.fetch_query(query)
        return _merge_rating_rows([self._row_to_dict(cols, row) for row in rows])

    def _latest_report_ratings(
        self, tickers: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Map latest stock_reports.rating JSON into the StockRating shape.

        Extracts scalar fields in SQL so we don't ship full rating JSON blobs
        (reasoning can be large) across the wire for the desk list.
        """
        db = get_db_client()
        ticker_clause = "AND ticker IN %s" if tickers else ""
        params = (tuple(tickers),) if tickers else None
        query = f"""
            SELECT DISTINCT ON (
                ticker, (rating->>'decision_ok') IS DISTINCT FROM 'false'
            )
                id,
                ticker,
                report_type,
                rating->>'rating' AS rating_tag,
                rating->>'score' AS score_raw,
                rating->>'confidence' AS confidence_raw,
                LEFT(COALESCE(rating->>'reasoning', ''), 280) AS reasoning,
                rating->'key_drivers' AS key_drivers,
                model,
                (rating->>'decision_ok') IS DISTINCT FROM 'false' AS decision_ok,
                COALESCE(rating->>'error', rating->>'error_message') AS error_message,
                created_at
            FROM stock_reports
            WHERE rating IS NOT NULL
              AND (
                  (rating->>'decision_ok') = 'false'
                  OR rating->>'rating' IS NOT NULL
              )
              {ticker_clause}
            ORDER BY
                ticker,
                (rating->>'decision_ok') IS DISTINCT FROM 'false',
                created_at DESC
        """
        if tickers:
            rows, _ = db.fetch_query(query, params)
        else:
            rows, _ = db.fetch_query(query)

        parsed: list[dict[str, Any]] = []
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
                decision_ok,
                error_message,
                created_at,
            ) = row
            if isinstance(key_drivers, str):
                try:
                    key_drivers = json.loads(key_drivers)
                except (json.JSONDecodeError, TypeError):
                    key_drivers = []
            score: int | None = None
            normalized_rating: str | None = None
            if decision_ok:
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
                    score = score_from_legacy_confidence(
                        str(rating_tag or "HOLD"), conf
                    )
                normalized_rating = normalize_rating(str(rating_tag or "HOLD"))

            created = created_at.isoformat() if hasattr(created_at, "isoformat") else created_at
            parsed.append({
                "id": report_id,
                "ticker": ticker,
                "rating": normalized_rating,
                "score": score,
                "reasoning": reasoning or "",
                "key_drivers": key_drivers or [],
                "supporting_headlines": [],
                "price_summary": {},
                "model": model,
                "created_at": created,
                "source": "report",
                "report_type": _normalize_report_type(report_type),
                "decision_ok": bool(decision_ok),
                "error_message": error_message,
            })
        return _merge_rating_rows(parsed)

    def get_rating_history(self, ticker: str) -> list[dict[str, Any]]:
        ticker = ticker.upper()
        db = get_db_client()
        rows, cols = db.fetch_query(
            f"""
            SELECT {RATING_SELECT}
            FROM stock_ratings
            WHERE ticker = %s
            ORDER BY created_at DESC
            """,
            (ticker,),
        )
        history = [self._row_to_dict(cols, row) for row in rows]

        report = next((r for r in self._latest_report_ratings([ticker]) if r["ticker"] == ticker), None)
        if report:
            if not history or history[0].get("created_at") != report.get("created_at"):
                if not history or (report.get("created_at") or "") >= (history[0].get("created_at") or ""):
                    history = [report] + history
        return history

    def get_latest_for_ticker(self, ticker: str) -> dict[str, Any] | None:
        ticker = ticker.upper()
        for r in self._latest_report_ratings([ticker]):
            if r["ticker"] == ticker:
                return r
        db = get_db_client()
        rows, cols = db.fetch_query(
            f"""
            SELECT {RATING_SELECT}
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
        decision_ok = bool(data.get("decision_ok", True))
        if decision_ok:
            score = data.get("score")
            if score is None and data.get("confidence") is not None:
                score = score_from_legacy_confidence(data.get("rating", "HOLD"), data.get("confidence"))
            score = clamp_score(score, 0)
            rating = normalize_rating(data.get("rating"))
        else:
            score = None
            rating = None
        report_type = _normalize_report_type(data.get("report_type"))

        db = get_db_client()
        db.execute_query(
            """
            INSERT INTO stock_ratings
                (ticker, rating, score, reasoning, key_drivers, supporting_headlines,
                 price_summary, model, report_type, decision_ok, error_message)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                report_type,
                decision_ok,
                data.get("error_message"),
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
        decision_ok = result.get("decision_ok") is not False
        result["decision_ok"] = decision_ok
        result["analysis_failed"] = not decision_ok
        if decision_ok:
            if "score" in result:
                result["score"] = clamp_score(result.get("score"))
            result["rating"] = normalize_rating(result.get("rating"))
        else:
            result["score"] = None
            result["rating"] = None
        result["report_type"] = _normalize_report_type(result.get("report_type"))
        result.setdefault("source", "analysis")
        return result
