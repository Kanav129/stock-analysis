from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from db.db_factory import get_db_client
from utils.logger import logger


@dataclass
class Position:
    ticker: str
    quantity: float
    avg_cost: Optional[float]
    market_price: Optional[float]
    market_value: Optional[float]
    unrealized_pnl: Optional[float]
    currency: str = "USD"


class HoldingsService:
    def _latest_snapshot_time(self) -> datetime | None:
        db = get_db_client()
        rows, _ = db.fetch_query(
            "SELECT MAX(snapshot_at) FROM holdings_snapshot"
        )
        if not rows or rows[0][0] is None:
            return None
        return rows[0][0]

    def current_tickers(self) -> list[str]:
        db = get_db_client()
        snapshot_at = self._latest_snapshot_time()
        if not snapshot_at:
            return []
        rows, _ = db.fetch_query(
            """
            SELECT DISTINCT ticker FROM holdings_snapshot
            WHERE snapshot_at = %s AND quantity <> 0
            ORDER BY ticker
            """,
            (snapshot_at,),
        )
        return [row[0] for row in rows]

    def _latest_closes(self, tickers: list[str]) -> dict[str, dict[str, Any]]:
        """Fetch latest close price and date per ticker from stock_data."""
        if not tickers:
            return {}
        db = get_db_client()
        rows, _ = db.fetch_query(
            """
            SELECT DISTINCT ON (ticker) ticker, close, bar_ts
            FROM stock_data
            WHERE ticker IN %s AND close IS NOT NULL
            ORDER BY ticker, bar_ts DESC
            """,
            (tuple(tickers),),
        )
        return {
            row[0]: {
                "close": float(row[1]) if row[1] is not None else None,
                "date": row[2].isoformat() if hasattr(row[2], "isoformat") else row[2],
            }
            for row in rows
        }

    def get_current_holdings(self) -> list[dict[str, Any]]:
        db = get_db_client()
        snapshot_at = self._latest_snapshot_time()
        if not snapshot_at:
            return []
        rows, cols = db.fetch_query(
            """
            SELECT account_id, ticker, quantity, avg_cost, market_price,
                   market_value, unrealized_pnl, currency, snapshot_at
            FROM holdings_snapshot
            WHERE snapshot_at = %s AND quantity <> 0
            ORDER BY ticker
            """,
            (snapshot_at,),
        )
        holdings = [
            {
                **dict(zip(cols, row)),
                "snapshot_at": row[cols.index("snapshot_at")].isoformat()
                if row[cols.index("snapshot_at")]
                else None,
            }
            for row in rows
        ]

        closes = self._latest_closes([h["ticker"] for h in holdings])
        for h in holdings:
            quote = closes.get(h["ticker"])
            if not quote or quote.get("close") is None:
                continue
            close = quote["close"]
            qty = float(h.get("quantity") or 0)
            avg_cost = h.get("avg_cost")
            h["market_price"] = close
            h["market_value"] = qty * close
            if avg_cost is not None:
                h["unrealized_pnl"] = (close - float(avg_cost)) * qty
            h["price_date"] = quote.get("date")

        return holdings

    def save_snapshot(self, positions: list[Position], account_id: str = "default") -> int:
        """Persist a holdings snapshot (e.g. from a one-off import script)."""
        db = get_db_client()
        snapshot_at = datetime.utcnow()
        count = 0
        for pos in positions:
            if pos.quantity == 0:
                continue
            db.create(
                "holdings_snapshot",
                {
                    "account_id": account_id,
                    "ticker": pos.ticker.upper(),
                    "quantity": pos.quantity,
                    "avg_cost": pos.avg_cost,
                    "market_price": pos.market_price,
                    "market_value": pos.market_value,
                    "unrealized_pnl": pos.unrealized_pnl,
                    "currency": pos.currency,
                    "snapshot_at": snapshot_at,
                },
            )
            count += 1
        logger.info(f"Saved {count} holdings at {snapshot_at}")
        return count

    def portfolio_summary(self) -> dict[str, Any]:
        holdings = self.get_current_holdings()
        total_value = sum(h.get("market_value") or 0 for h in holdings)
        total_pnl = sum(h.get("unrealized_pnl") or 0 for h in holdings)
        price_dates = [h.get("price_date") for h in holdings if h.get("price_date")]
        snapshot_at = self._latest_snapshot_time()
        return {
            "total_value": total_value,
            "total_unrealized_pnl": total_pnl,
            "position_count": len(holdings),
            "snapshot_at": max(price_dates) if price_dates else (
                snapshot_at.isoformat() if snapshot_at else None
            ),
        }
