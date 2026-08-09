"""Persist and accept AI watchlist suggestions (7-day expiry)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg2.extras import Json

from db.db_factory import get_db_client
from services.job_queue_service import JOB_CORE, job_queue_service
from services.watchlist_service import WatchlistService
from utils.logger import logger

SUGGESTION_TTL_DAYS = 7

_LIST_COLS = (
    "ticker, reason, suggested_at, expires_at, source, "
    "company_name, company_blurb, sector, industry"
)
_DETAIL_COLS = _LIST_COLS + ", brief"


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _parse_brief(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _row_to_item(row: tuple, cols: list[str], *, include_brief: bool) -> dict[str, Any]:
    item = dict(zip(cols, row))
    item["suggested_at"] = _iso(item.get("suggested_at"))
    item["expires_at"] = _iso(item.get("expires_at"))
    if include_brief:
        item["brief"] = _parse_brief(item.get("brief"))
    elif "brief" in item:
        del item["brief"]
    return item


class SuggestionService:
    def purge_expired(self) -> int:
        db = get_db_client()
        rows, _ = db.fetch_query(
            """
            DELETE FROM watchlist_suggestions
            WHERE expires_at <= NOW()
            RETURNING ticker
            """
        )
        return len(rows or [])

    def list_active(self) -> list[dict[str, Any]]:
        self.purge_expired()
        db = get_db_client()
        rows, cols = db.fetch_query(
            f"""
            SELECT {_LIST_COLS}
            FROM watchlist_suggestions
            WHERE expires_at > NOW()
            ORDER BY suggested_at DESC
            """
        )
        return [_row_to_item(row, cols, include_brief=False) for row in (rows or [])]

    def get(self, ticker: str) -> dict[str, Any] | None:
        self.purge_expired()
        ticker = ticker.upper().strip()
        db = get_db_client()
        rows, cols = db.fetch_query(
            f"""
            SELECT {_DETAIL_COLS}
            FROM watchlist_suggestions
            WHERE ticker = %s AND expires_at > NOW()
            """,
            (ticker,),
        )
        if not rows:
            return None
        return _row_to_item(rows[0], cols, include_brief=True)

    def upsert_ranked(self, items: list[dict[str, Any]]) -> int:
        """Insert or renew suggestions. Requires non-empty brief per item."""
        if not items:
            return 0
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=SUGGESTION_TTL_DAYS)
        db = get_db_client()
        count = 0
        for raw in items:
            ticker = str(raw.get("ticker") or "").upper().strip()
            reason = str(raw.get("reason") or "").strip()
            brief = raw.get("brief")
            if not ticker or not reason or not isinstance(brief, dict) or not brief:
                continue
            source = raw.get("source")
            source_s = str(source).strip()[:16] if source else None
            company_name = (str(raw.get("company_name") or "").strip() or None)
            company_blurb = (str(raw.get("company_blurb") or "").strip() or None)
            sector = (str(raw.get("sector") or "").strip() or None)
            industry = (str(raw.get("industry") or "").strip() or None)
            db.execute_query(
                """
                INSERT INTO watchlist_suggestions (
                    ticker, reason, suggested_at, expires_at, source,
                    company_name, company_blurb, sector, industry, brief
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker) DO UPDATE SET
                    reason = EXCLUDED.reason,
                    suggested_at = EXCLUDED.suggested_at,
                    expires_at = EXCLUDED.expires_at,
                    source = COALESCE(EXCLUDED.source, watchlist_suggestions.source),
                    company_name = EXCLUDED.company_name,
                    company_blurb = EXCLUDED.company_blurb,
                    sector = EXCLUDED.sector,
                    industry = EXCLUDED.industry,
                    brief = EXCLUDED.brief
                """,
                (
                    ticker,
                    reason[:500],
                    now,
                    expires,
                    source_s,
                    company_name,
                    company_blurb,
                    sector,
                    industry,
                    Json(brief),
                ),
            )
            count += 1
        logger.info("Upserted %s watchlist suggestion(s)", count)
        return count

    def delete(self, ticker: str) -> bool:
        ticker = ticker.upper().strip()
        db = get_db_client()
        db.execute_query(
            "DELETE FROM watchlist_suggestions WHERE ticker = %s",
            (ticker,),
        )
        return True

    def accept(self, ticker: str) -> dict[str, Any]:
        """Add to watchlist, enqueue core analysis, remove suggestion."""
        ticker = ticker.upper().strip()
        if not ticker:
            raise ValueError("ticker is required")

        item = WatchlistService().add(ticker, notes="Added from AI suggestion")
        enqueue_result = job_queue_service.enqueue(JOB_CORE, [ticker])
        self.delete(ticker)
        return {
            "item": item,
            "job": enqueue_result,
            "ticker": ticker,
        }
