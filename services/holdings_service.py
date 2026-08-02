from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from psycopg2.extras import Json, execute_values

from db.db_factory import get_db_client
from utils.logger import logger

HOLDINGS_META_KEY = "holdings_current_snapshot"

INSERT_SQL = """
INSERT INTO holdings_snapshot (
    account_id, ticker, quantity, avg_cost, market_price, market_value,
    unrealized_pnl, currency, snapshot_at, conid, asset_class, description,
    exchange, side, multiplier, report_date, ibkr_mark_price, ibkr_position_value,
    cost_basis_money, cost_basis_price, ibkr_unrealized_pnl, percent_of_nav,
    fx_rate_to_base, raw_symbol, source, source_data
) VALUES %s
"""


@dataclass
class Position:
    ticker: str
    quantity: float
    avg_cost: Optional[float]
    market_price: Optional[float]
    market_value: Optional[float]
    unrealized_pnl: Optional[float]
    currency: str = "USD"
    account_id: str = "default"
    conid: Optional[str] = None
    asset_class: Optional[str] = None
    description: Optional[str] = None
    exchange: Optional[str] = None
    side: Optional[str] = None
    multiplier: Optional[float] = None
    report_date: Optional[str] = None
    ibkr_mark_price: Optional[float] = None
    ibkr_position_value: Optional[float] = None
    cost_basis_money: Optional[float] = None
    cost_basis_price: Optional[float] = None
    ibkr_unrealized_pnl: Optional[float] = None
    percent_of_nav: Optional[float] = None
    fx_rate_to_base: Optional[float] = None
    raw_symbol: Optional[str] = None
    source: str = "manual"
    source_data: dict[str, Any] = field(default_factory=dict)


class HoldingsService:
    def _load_meta(self) -> dict[str, Any] | None:
        db = get_db_client()
        try:
            rows, _ = db.fetch_query(
                "SELECT value FROM app_settings WHERE key = %s",
                (HOLDINGS_META_KEY,),
            )
        except Exception:
            return None
        if not rows or rows[0][0] is None:
            return None
        raw = rows[0][0]
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            return None
        return data if isinstance(data, dict) else None

    def _save_meta(self, meta: dict[str, Any], *, conn=None) -> None:
        payload = json.dumps(meta)
        sql = """
        INSERT INTO app_settings (key, value, updated_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
        """
        if conn is not None:
            with conn.cursor() as cur:
                cur.execute(sql, (HOLDINGS_META_KEY, payload))
            return
        get_db_client().execute_query(sql, (HOLDINGS_META_KEY, payload))

    def _latest_snapshot_time(self) -> datetime | None:
        meta = self._load_meta()
        if meta and meta.get("snapshot_at"):
            raw = meta["snapshot_at"]
            try:
                dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                return dt
            except ValueError:
                pass
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
                   market_value, unrealized_pnl, currency, snapshot_at,
                   conid, asset_class, description, exchange, side, multiplier,
                   report_date, ibkr_mark_price, ibkr_position_value,
                   cost_basis_money, cost_basis_price, ibkr_unrealized_pnl,
                   percent_of_nav, fx_rate_to_base, raw_symbol, source, source_data
            FROM holdings_snapshot
            WHERE snapshot_at = %s AND quantity <> 0
            ORDER BY ticker
            """,
            (snapshot_at,),
        )
        holdings = []
        for row in rows:
            item = dict(zip(cols, row))
            if item.get("snapshot_at") and hasattr(item["snapshot_at"], "isoformat"):
                item["snapshot_at"] = item["snapshot_at"].isoformat()
            if isinstance(item.get("source_data"), str):
                try:
                    item["source_data"] = json.loads(item["source_data"])
                except (json.JSONDecodeError, TypeError):
                    item["source_data"] = {}
            holdings.append(item)

        closes = self._latest_closes([h["ticker"] for h in holdings])
        for h in holdings:
            # Preserve IBKR statement values; recompute live desk marks from stock_data.
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

    def save_snapshot(
        self, positions: list[Position], account_id: str = "default"
    ) -> dict[str, Any]:
        """Persist a holdings snapshot (legacy helper for one-off imports)."""
        snapshot_at = datetime.now(timezone.utc)
        rows: list[Position] = []
        for pos in positions:
            if pos.quantity == 0:
                continue
            if not pos.account_id or pos.account_id == "default":
                pos.account_id = account_id
            rows.append(pos)
        return self.replace_snapshot(rows, snapshot_at=snapshot_at, source="manual")

    def replace_snapshot(
        self,
        positions: list[Position],
        *,
        snapshot_at: datetime | None = None,
        source: str = "ibkr_flex",
        skipped: int = 0,
    ) -> dict[str, Any]:
        """Atomically publish a full-book snapshot (may be empty).

        Inserts all rows under one snapshot_at and updates app_settings so an
        empty successful import becomes the current book. Callers must only
        invoke this after a successful parse — never on fetch failures.
        """
        snapshot_at = snapshot_at or datetime.now(timezone.utc)
        if snapshot_at.tzinfo is None:
            snapshot_at = snapshot_at.replace(tzinfo=timezone.utc)

        usable = [p for p in positions if p.quantity != 0]
        db = get_db_client()
        values = []
        for pos in usable:
            values.append(
                (
                    pos.account_id or "default",
                    pos.ticker.upper(),
                    float(pos.quantity),
                    pos.avg_cost,
                    pos.market_price,
                    pos.market_value,
                    pos.unrealized_pnl,
                    pos.currency or "USD",
                    snapshot_at,
                    pos.conid,
                    pos.asset_class,
                    pos.description,
                    pos.exchange,
                    pos.side,
                    pos.multiplier,
                    pos.report_date,
                    pos.ibkr_mark_price,
                    pos.ibkr_position_value,
                    pos.cost_basis_money,
                    pos.cost_basis_price,
                    pos.ibkr_unrealized_pnl,
                    pos.percent_of_nav,
                    pos.fx_rate_to_base,
                    pos.raw_symbol,
                    pos.source or source,
                    Json(pos.source_data or {}),
                )
            )

        meta = {
            "snapshot_at": snapshot_at.isoformat(),
            "source": source,
            "saved": len(usable),
            "skipped": skipped,
            "tickers": sorted({p.ticker.upper() for p in usable}),
        }

        with db.checkout() as conn:
            try:
                with conn.cursor() as cur:
                    if values:
                        execute_values(cur, INSERT_SQL, values, page_size=200)
                    cur.execute(
                        """
                        INSERT INTO app_settings (key, value, updated_at)
                        VALUES (%s, %s, NOW())
                        ON CONFLICT (key) DO UPDATE
                          SET value = EXCLUDED.value, updated_at = NOW()
                        """,
                        (HOLDINGS_META_KEY, json.dumps(meta)),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        logger.info(
            "Saved holdings snapshot source=%s count=%s skipped=%s at %s",
            source,
            len(usable),
            skipped,
            snapshot_at.isoformat(),
        )
        return meta

    def sync_metadata(self) -> dict[str, Any]:
        meta = self._load_meta() or {}
        snapshot_at = self._latest_snapshot_time()
        return {
            "holdings_synced_at": meta.get("snapshot_at")
            or (snapshot_at.isoformat() if snapshot_at else None),
            "source": meta.get("source"),
            "saved": meta.get("saved"),
            "skipped": meta.get("skipped"),
        }

    def _prior_daily_closes(self, tickers: list[str]) -> dict[str, float]:
        """Most recent completed daily close per ticker (for day-change vs latest mark)."""
        if not tickers:
            return {}
        db = get_db_client()
        rows, _ = db.fetch_query(
            """
            SELECT ticker, close, rn
            FROM (
                SELECT ticker, close,
                       ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn
                FROM stock_data
                WHERE ticker IN %s
                  AND bar_interval = '1d'
                  AND close IS NOT NULL
            ) ranked
            WHERE rn <= 2
            """,
            (tuple(tickers),),
        )
        latest: dict[str, float] = {}
        prior: dict[str, float] = {}
        for ticker, close, rn in rows:
            price = float(close)
            if rn == 1:
                latest[ticker] = price
            elif rn == 2:
                prior[ticker] = price
        return {t: prior.get(t, latest[t]) for t in latest}

    def portfolio_summary(self) -> dict[str, Any]:
        holdings = self.get_current_holdings()
        total_value = sum(h.get("market_value") or 0 for h in holdings)
        total_pnl = sum(h.get("unrealized_pnl") or 0 for h in holdings)
        price_dates = [h.get("price_date") for h in holdings if h.get("price_date")]
        meta = self.sync_metadata()
        snapshot_at = self._latest_snapshot_time()

        cost_basis = 0.0
        has_cost = False
        for h in holdings:
            avg_cost = h.get("avg_cost")
            qty = float(h.get("quantity") or 0)
            if avg_cost is not None and qty:
                cost_basis += float(avg_cost) * qty
                has_cost = True
        if not has_cost:
            cost_basis = total_value - total_pnl

        overall_change_pct = None
        if cost_basis:
            overall_change_pct = round(total_pnl / cost_basis * 100, 2)

        prior_closes = self._prior_daily_closes([h["ticker"] for h in holdings])
        prior_value = 0.0
        day_dollar = 0.0
        for h in holdings:
            ticker = h["ticker"]
            qty = float(h.get("quantity") or 0)
            prior = prior_closes.get(ticker)
            latest = h.get("market_price")
            if prior is None or not qty:
                continue
            prior_value += qty * prior
            if latest is not None:
                day_dollar += qty * (float(latest) - prior)

        day_change_pct = None
        day_change_value = None
        if prior_value:
            day_change_pct = round(day_dollar / prior_value * 100, 2)
            day_change_value = round(day_dollar, 2)

        return {
            "total_value": total_value,
            "total_unrealized_pnl": total_pnl,
            "day_change_pct": day_change_pct,
            "day_change_value": day_change_value,
            "overall_change_pct": overall_change_pct,
            "position_count": len(holdings),
            "snapshot_at": max(price_dates) if price_dates else (
                snapshot_at.isoformat() if snapshot_at else None
            ),
            "holdings_synced_at": meta.get("holdings_synced_at"),
            "source": meta.get("source"),
        }
