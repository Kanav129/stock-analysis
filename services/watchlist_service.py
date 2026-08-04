from __future__ import annotations

from typing import Any

from db.db_factory import get_db_client
from services.ratings_service import RatingsService


class WatchlistService:
    def list_items(self) -> list[dict[str, Any]]:
        items = self._fetch_items()
        return self._enrich_items(items)

    def _fetch_items(self) -> list[dict[str, Any]]:
        db = get_db_client()
        rows, cols = db.fetch_query(
            "SELECT id, ticker, notes, added_at FROM watchlist ORDER BY added_at DESC"
        )
        items = []
        for row in rows:
            item = dict(zip(cols, row))
            if item.get("added_at"):
                item["added_at"] = item["added_at"].isoformat()
            items.append(item)
        return items

    def _enrich_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not items:
            return []

        tickers = [item["ticker"] for item in items]
        price_map = self._latest_prices(tickers)
        rating_map = {r["ticker"]: r for r in RatingsService().get_latest_ratings()}

        for item in items:
            ticker = item["ticker"]
            rating = rating_map.get(ticker)
            price = price_map.get(ticker)

            item["rating"] = rating["rating"] if rating else None
            item["score"] = rating["score"] if rating else None
            item["report_type"] = rating.get("report_type") if rating else None
            item["analysis_failed"] = bool(
                rating and rating.get("analysis_failed")
            )
            item["analysis_error"] = rating.get("analysis_error") if rating else None
            item["failed_at"] = rating.get("failed_at") if rating else None
            item["latest_price"] = price["close"] if price else None
            item["price_date"] = price["date"] if price else None
            item["description"] = self._build_description(item, rating)

        return items

    @staticmethod
    def _build_description(item: dict[str, Any], rating: dict[str, Any] | None) -> str | None:
        if rating and rating.get("reasoning"):
            text = str(rating["reasoning"]).strip()
            if len(text) > 160:
                return f"{text[:157]}..."
            return text
        if item.get("notes"):
            return str(item["notes"]).strip()
        return None

    @staticmethod
    def _latest_prices(tickers: list[str]) -> dict[str, dict[str, Any]]:
        db = get_db_client()
        rows, cols = db.fetch_query(
            """
            SELECT DISTINCT ON (ticker) ticker, close, bar_ts AS date
            FROM stock_data
            WHERE ticker = ANY(%s)
            ORDER BY ticker, bar_ts DESC
            """,
            (tickers,),
        )
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            record = dict(zip(cols, row))
            if record.get("date") and hasattr(record["date"], "isoformat"):
                record["date"] = record["date"].isoformat()
            if record.get("close") is not None:
                record["close"] = float(record["close"])
            result[record["ticker"]] = record
        return result

    def add(self, ticker: str, notes: str | None = None) -> dict[str, Any]:
        ticker = ticker.upper().strip()
        db = get_db_client()
        db.execute_query(
            """
            INSERT INTO watchlist (ticker, notes)
            VALUES (%s, %s)
            ON CONFLICT (ticker) DO UPDATE SET notes = EXCLUDED.notes
            """,
            (ticker, notes),
        )
        rows, cols = db.fetch_query(
            "SELECT id, ticker, notes, added_at FROM watchlist WHERE ticker = %s",
            (ticker,),
        )
        item = dict(zip(cols, rows[0]))
        if item.get("added_at"):
            item["added_at"] = item["added_at"].isoformat()
        return item

    def remove(self, ticker: str) -> bool:
        ticker = ticker.upper().strip()
        db = get_db_client()
        db.execute_query("DELETE FROM watchlist WHERE ticker = %s", (ticker,))
        return True

    def tickers(self) -> list[str]:
        db = get_db_client()
        rows, _ = db.fetch_query("SELECT ticker FROM watchlist ORDER BY ticker")
        return [row[0] for row in rows]
