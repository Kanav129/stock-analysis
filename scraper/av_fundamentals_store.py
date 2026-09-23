"""Durable Alpha Vantage statement snapshots. Render's disk does not survive sleep."""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Optional

from psycopg2.extras import Json

from db.db_factory import get_db_client


class AvFundamentalsStore:
    def load(self, ticker: str) -> Optional[dict[str, Any]]:
        symbol = (ticker or "").strip().upper()
        if not symbol:
            return None
        db = get_db_client()
        rows, cols = db.fetch_query(
            """
            SELECT ticker, fiscal_date_ending, fetched_at, checked_at, snapshot
            FROM av_fundamentals
            WHERE ticker = %s
            """,
            (symbol,),
        )
        if not rows:
            return None
        data = dict(zip(cols, rows[0]))
        snapshot = data.get("snapshot") or {}
        if isinstance(snapshot, str):
            snapshot = json.loads(snapshot)
        if not isinstance(snapshot, dict):
            return None
        return {
            "ticker": data["ticker"],
            "fiscal_date_ending": data.get("fiscal_date_ending"),
            "fetched_at": data.get("fetched_at"),
            "checked_at": data.get("checked_at"),
            "snapshot": snapshot,
        }

    def save(
        self,
        ticker: str,
        *,
        snapshot: dict[str, Any],
        fiscal_date_ending: Optional[date],
        fetched_at: datetime,
        checked_at: datetime,
    ) -> None:
        symbol = (ticker or "").strip().upper()
        db = get_db_client()
        db.execute_query(
            """
            INSERT INTO av_fundamentals (
                ticker, fiscal_date_ending, fetched_at, checked_at, snapshot
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (ticker) DO UPDATE SET
                fiscal_date_ending = EXCLUDED.fiscal_date_ending,
                fetched_at = EXCLUDED.fetched_at,
                checked_at = EXCLUDED.checked_at,
                snapshot = EXCLUDED.snapshot
            """,
            (symbol, fiscal_date_ending, fetched_at, checked_at, Json(snapshot)),
        )
