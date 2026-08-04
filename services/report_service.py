"""Research report service — DB operations for stock_reports table."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from db.db_factory import get_db_client
from utils.logger import logger


def resolve_report_type_filter(value: str | None) -> str | None:
    """Map API ``type`` query values to a DB filter.

    Returns ``None`` for "any type / chronologically latest" (``latest``, ``any``,
    empty, or omitted). Returns ``core`` / ``deep`` when filtered. Raises
    ``ValueError`` for unknown values.
    """
    if value is None:
        return None
    raw = str(value).strip().lower()
    if raw in ("", "latest", "any"):
        return None
    if raw in ("core", "deep"):
        return raw
    raise ValueError("type must be core, deep, or latest")


class ReportService:
    """CRUD for stock_reports — generated research artifacts stored as JSONB."""

    def __init__(self) -> None:
        self._db = get_db_client()

    def save_report(
        self,
        ticker: str,
        report_type: str,
        sections: dict[str, Any],
        rating: Optional[dict[str, Any]] = None,
        factor_scores: Optional[dict[str, Any]] = None,
        entry_levels: Optional[dict[str, Any]] = None,
        live_price: Optional[float] = None,
        model: Optional[str] = None,
    ) -> int:
        """Insert a new report row. Returns the new row id."""
        data = {
            "ticker": ticker.upper(),
            "report_type": report_type,
            "sections": json.dumps(sections),
            "rating": json.dumps(rating) if rating else None,
            "factor_scores": json.dumps(factor_scores) if factor_scores else None,
            "entry_levels": json.dumps(entry_levels) if entry_levels else None,
            "live_price": live_price,
            "model": model,
            "created_at": datetime.utcnow().isoformat(),
        }
        self._db.create("stock_reports", data)
        # Fetch the id of the row we just inserted
        rows, _ = self._db.fetch_query(
            "SELECT id FROM stock_reports WHERE ticker=%s AND report_type=%s "
            "ORDER BY created_at DESC LIMIT 1",
            (ticker.upper(), report_type),
        )
        new_id = rows[0][0] if rows else -1
        logger.info(f"Saved {report_type} report {new_id} for {ticker}")
        return new_id

    def get_latest_report(
        self, ticker: str, report_type: str | None = "core"
    ) -> Optional[dict[str, Any]]:
        """Return the most recent report for a ticker.

        When ``report_type`` is set (``core`` / ``deep``), filter to that type.
        When ``report_type`` is ``None``, return the chronologically newest row
        of any type (needed so weekly core analysis is not hidden by an older
        deep dive on the stock page).
        """
        if report_type:
            rows, cols = self._db.fetch_query(
                "SELECT id, ticker, report_type, sections, rating, factor_scores, "
                "entry_levels, live_price, model, created_at "
                "FROM stock_reports "
                "WHERE ticker=%s AND report_type=%s "
                "ORDER BY created_at DESC LIMIT 1",
                (ticker.upper(), report_type),
            )
        else:
            rows, cols = self._db.fetch_query(
                "SELECT id, ticker, report_type, sections, rating, factor_scores, "
                "entry_levels, live_price, model, created_at "
                "FROM stock_reports "
                "WHERE ticker=%s "
                "ORDER BY created_at DESC LIMIT 1",
                (ticker.upper(),),
            )
        if not rows:
            return None
        return self._row_to_dict(rows[0], cols)

    def list_latest_reports_by_ticker(self) -> list[dict[str, Any]]:
        """Latest report per ticker (any type), for rescoring."""
        rows, cols = self._db.fetch_query(
            """
            SELECT DISTINCT ON (ticker)
                id, ticker, report_type, sections, rating, factor_scores,
                entry_levels, live_price, model, created_at
            FROM stock_reports
            ORDER BY ticker, created_at DESC
            """
        )
        return [self._row_to_dict(r, cols) for r in rows]

    def update_report_rating(
        self,
        report_id: int,
        rating: dict[str, Any],
        entry_levels: Optional[dict[str, Any]] = None,
        model: Optional[str] = None,
    ) -> None:
        """Update rating (and optional entry_levels/model) on an existing report."""
        if entry_levels is not None:
            self._db.execute_query(
                """
                UPDATE stock_reports
                SET rating = %s, entry_levels = %s, model = COALESCE(%s, model)
                WHERE id = %s
                """,
                (json.dumps(rating), json.dumps(entry_levels), model, report_id),
            )
        else:
            self._db.execute_query(
                """
                UPDATE stock_reports
                SET rating = %s, model = COALESCE(%s, model)
                WHERE id = %s
                """,
                (json.dumps(rating), model, report_id),
            )
        logger.info(f"Updated rating on report {report_id}")

    def get_report_by_id(self, ticker: str, report_id: int) -> Optional[dict[str, Any]]:
        """Return one report scoped to ticker, or None."""
        rows, cols = self._db.fetch_query(
            "SELECT id, ticker, report_type, sections, rating, factor_scores, "
            "entry_levels, live_price, model, created_at "
            "FROM stock_reports "
            "WHERE id=%s AND ticker=%s "
            "LIMIT 1",
            (int(report_id), ticker.upper()),
        )
        if not rows:
            return None
        return self._row_to_dict(rows[0], cols)

    def get_report_history(self, ticker: str) -> list[dict[str, Any]]:
        """List reports for a ticker newest-first, with rating/score for the desk tile."""
        rows, cols = self._db.fetch_query(
            """
            SELECT
                id,
                ticker,
                report_type,
                created_at,
                rating->>'rating' AS rating,
                rating->>'score' AS score
            FROM stock_reports
            WHERE ticker=%s
            ORDER BY created_at DESC
            """,
            (ticker.upper(),),
        )
        items: list[dict[str, Any]] = []
        for row in rows:
            item = self._row_to_dict(row, cols)
            raw_score = item.get("score")
            if raw_score is None or raw_score == "":
                item["score"] = None
            else:
                try:
                    item["score"] = int(float(raw_score))
                except (TypeError, ValueError):
                    item["score"] = None
            if not item.get("rating"):
                item["rating"] = None
            items.append(item)
        return items

    @staticmethod
    def _row_to_dict(row: tuple, cols: list[str]) -> dict[str, Any]:
        result = dict(zip(cols, row))
        for key in ("sections", "rating", "factor_scores", "entry_levels"):
            val = result.get(key)
            if isinstance(val, str):
                try:
                    result[key] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass
        if result.get("created_at") and isinstance(result["created_at"], datetime):
            result["created_at"] = result["created_at"].isoformat()
        return result