"""Price sync: multi-resolution ladder for smooth charts.

Intervals kept (after compaction):
  1m  ~2d   → chart 1D
  15m ~8d   → chart 7D
  30m ~16d  → chart 2W
  1h  ~35d  → chart 1M
  1d  forever → chart 3M+

Daily sync gap-fills each band from Yahoo, then compacts aged fine bars
into coarser intervals. Legacy ``5m`` rows are migrated once then deleted.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

from db.postgres_db import PostgresDBClient
from utils.logger import logger

BAR_1D = "1d"
BAR_1M = "1m"
BAR_15M = "15m"
BAR_30M = "30m"
BAR_1H = "1h"
BAR_5M_LEGACY = "5m"

# Snap bar timestamps to interval grids (seconds).
SNAP_SEC = {
    BAR_1M: 60,
    BAR_15M: 900,
    BAR_30M: 1800,
    BAR_1H: 3600,
}

# Retention windows (calendar days) and Yahoo fetch policy per band.
BANDS: dict[str, dict[str, Any]] = {
    BAR_1M: {
        "keep_days": 2,
        "fresh_age": timedelta(hours=36),
        "short_period": "2d",
        "long_period": "7d",
    },
    BAR_15M: {
        "keep_days": 8,
        "fresh_age": timedelta(days=3),
        "short_period": "5d",
        "long_period": "1mo",
    },
    BAR_30M: {
        "keep_days": 16,
        "fresh_age": timedelta(days=4),
        "short_period": "5d",
        "long_period": "1mo",
    },
    BAR_1H: {
        "keep_days": 35,
        "fresh_age": timedelta(days=4),
        "short_period": "5d",
        "long_period": "1mo",
    },
    BAR_1D: {
        "keep_days": None,
        "fresh_age": timedelta(days=4),
        "short_period": "5d",
        "long_period": "1mo",
    },
}

# Compact fine → coarse when past fine retention.
COMPACTION_STEPS: list[tuple[str, str]] = [
    (BAR_1M, BAR_15M),
    (BAR_15M, BAR_30M),
    (BAR_30M, BAR_1H),
    (BAR_1H, BAR_1D),
]

UPSERT_SQL = """
INSERT INTO stock_data (ticker, date, bar_ts, bar_interval, open, high, low, close, volume)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (ticker, bar_ts, bar_interval) DO UPDATE SET
    date = EXCLUDED.date,
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume
"""


def _to_python(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and value != value:  # NaN
        return None
    return value


def _as_utc_ts(value: Any) -> datetime:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.to_pydatetime()


def _daily_bar_ts(value: Any) -> datetime:
    """Normalize daily bars to UTC midnight of the trading date (no intraday dupes)."""
    ts = _as_utc_ts(value)
    day = ts.date()
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def _snap_ts(ts: datetime, interval: str) -> datetime:
    if interval == BAR_1D:
        return _daily_bar_ts(ts)
    step = SNAP_SEC[interval]
    epoch = int(ts.timestamp())
    snapped = epoch - (epoch % step)
    return datetime.fromtimestamp(snapped, tz=timezone.utc)


class StockDataScraper:
    def __init__(self) -> None:
        self.db_client = self.initialize_db_client()

    @staticmethod
    def initialize_db_client() -> PostgresDBClient:
        load_dotenv()
        return PostgresDBClient(
            host=os.getenv("POSTGRES_HOST"),
            database=os.getenv("POSTGRES_DB"),
            user=os.getenv("POSTGRES_USERNAME"),
            password=os.getenv("POSTGRES_PASSWORD"),
            port=os.getenv("POSTGRES_PORT", 5432),
        )

    def fetch_history(self, ticker: str, period: str, interval: str) -> pd.DataFrame:
        ticker_data = yf.Ticker(ticker)
        return ticker_data.history(period=period, interval=interval, auto_adjust=False)

    def _row_params(
        self,
        ticker: str,
        bar_ts: datetime,
        bar_interval: str,
        row: pd.Series,
    ) -> tuple:
        trade_date = bar_ts.astimezone(timezone.utc).date()
        return (
            ticker,
            trade_date,
            bar_ts,
            bar_interval,
            _to_python(row.get("Open")),
            _to_python(row.get("High")),
            _to_python(row.get("Low")),
            _to_python(row.get("Close")),
            int(_to_python(row.get("Volume")) or 0),
        )

    def upsert_daily_frame(self, ticker: str, frame: pd.DataFrame) -> int:
        if frame is None or frame.empty:
            return 0
        rows = [
            self._row_params(ticker, _daily_bar_ts(idx), BAR_1D, row)
            for idx, row in frame.iterrows()
        ]
        return self.db_client.execute_many(UPSERT_SQL, rows)

    def upsert_interval_frame(self, ticker: str, frame: pd.DataFrame, interval: str) -> int:
        """Upsert OHLCV bars for a non-daily interval (snapped to grid)."""
        if frame is None or frame.empty:
            return 0
        if interval == BAR_1D:
            return self.upsert_daily_frame(ticker, frame)
        rows = [
            self._row_params(ticker, _snap_ts(_as_utc_ts(idx), interval), interval, row)
            for idx, row in frame.iterrows()
        ]
        return self.db_client.execute_many(UPSERT_SQL, rows)

    # Back-compat name used by older tests / callers
    def upsert_intraday_frame(self, ticker: str, frame: pd.DataFrame, interval: str = BAR_1M) -> int:
        return self.upsert_interval_frame(ticker, frame, interval)

    def _latest_bar_ts(self, ticker: str, interval: str) -> Optional[datetime]:
        rows, _ = self.db_client.fetch_query(
            """
            SELECT MAX(bar_ts) AS latest
            FROM stock_data
            WHERE ticker = %s AND bar_interval = %s
            """,
            (ticker, interval),
        )
        if not rows or rows[0][0] is None:
            return None
        latest = rows[0][0]
        if latest.tzinfo is None:
            return latest.replace(tzinfo=timezone.utc)
        return latest

    def _fetch_period_for_band(self, ticker: str, interval: str) -> str:
        cfg = BANDS[interval]
        latest = self._latest_bar_ts(ticker, interval)
        if latest is None:
            return cfg["long_period"]
        age = datetime.now(timezone.utc) - latest
        if age <= cfg["fresh_age"]:
            return cfg["short_period"]
        return cfg["long_period"]

    def sync_band(
        self,
        ticker: str,
        interval: str,
        on_detail: Optional[Callable[[str], None]] = None,
    ) -> int:
        """Gap-fill one resolution band from Yahoo."""
        period = self._fetch_period_for_band(ticker, interval)
        cfg = BANDS[interval]
        mode = "refresh" if period == cfg["short_period"] else "backfill"
        if on_detail:
            on_detail(f"{ticker} · fetch {interval} · {mode} ({period})")
        frame = self.fetch_history(ticker, period=period, interval=interval)
        if (frame is None or frame.empty) and period != BANDS[interval]["short_period"]:
            if on_detail:
                on_detail(
                    f"{ticker} · fetch {interval} · retry short window "
                    f"({BANDS[interval]['short_period']})"
                )
            frame = self.fetch_history(
                ticker, period=BANDS[interval]["short_period"], interval=interval
            )
        if on_detail:
            on_detail(f"{ticker} · upsert {interval} bars…")
        n = self.upsert_interval_frame(ticker, frame, interval)
        logger.info(f"{ticker}: upserted {n} {interval} bar(s) (period={period})")
        if on_detail:
            on_detail(f"{ticker} · {interval} done · {n} bar(s) · {mode} ({period})")
        return n

    def refresh_live_1m(self, ticker: str) -> int:
        """Light intraday backfill: today's 1m bars (covers session + last few minutes)."""
        ticker = ticker.upper().strip()
        frame = self.fetch_history(ticker, period="1d", interval=BAR_1M)
        if frame is None or frame.empty:
            frame = self.fetch_history(ticker, period="2d", interval=BAR_1M)
        n = self.upsert_interval_frame(ticker, frame, BAR_1M)
        logger.info(f"{ticker}: live-refresh upserted {n} 1m bar(s)")
        return n

    def _aggregate_aged_bars(
        self,
        ticker: str,
        source_interval: str,
        target_interval: str,
        cutoff: datetime,
    ) -> int:
        """Aggregate source bars older than cutoff into target interval buckets."""
        if target_interval == BAR_1D:
            rows, _ = self.db_client.fetch_query(
                """
                SELECT trade_date, open, high, low, close, volume
                FROM (
                    SELECT DISTINCT ON (((bar_ts AT TIME ZONE 'UTC')::date))
                        (bar_ts AT TIME ZONE 'UTC')::date AS trade_date,
                        open, high, low, close, volume
                    FROM stock_data
                    WHERE ticker = %s
                      AND bar_interval = %s
                      AND bar_ts < %s
                    ORDER BY (bar_ts AT TIME ZONE 'UTC')::date, bar_ts DESC
                ) aged
                """,
                (ticker, source_interval, cutoff),
            )
            upsert_rows = []
            for trade_date, open_, high, low, close, volume in rows or []:
                bar_ts = datetime(
                    trade_date.year, trade_date.month, trade_date.day, tzinfo=timezone.utc
                )
                upsert_rows.append(
                    (
                        ticker,
                        trade_date,
                        bar_ts,
                        BAR_1D,
                        open_,
                        high,
                        low,
                        close,
                        int(volume or 0),
                    )
                )
            if upsert_rows:
                self.db_client.execute_many(UPSERT_SQL, upsert_rows)
            return len(upsert_rows)

        step = SNAP_SEC[target_interval]
        rows, _ = self.db_client.fetch_query(
            """
            SELECT
                to_timestamp(floor(extract(epoch FROM bar_ts) / %s) * %s) AS bucket,
                (array_agg(open ORDER BY bar_ts ASC))[1] AS open,
                MAX(high) AS high,
                MIN(low) AS low,
                (array_agg(close ORDER BY bar_ts DESC))[1] AS close,
                COALESCE(SUM(volume), 0) AS volume
            FROM stock_data
            WHERE ticker = %s
              AND bar_interval = %s
              AND bar_ts < %s
            GROUP BY 1
            ORDER BY 1
            """,
            (step, step, ticker, source_interval, cutoff),
        )
        upsert_rows = []
        for bucket, open_, high, low, close, volume in rows or []:
            bar_ts = bucket
            if getattr(bar_ts, "tzinfo", None) is None:
                bar_ts = bar_ts.replace(tzinfo=timezone.utc)
            else:
                bar_ts = bar_ts.astimezone(timezone.utc)
            trade_date = bar_ts.date()
            upsert_rows.append(
                (
                    ticker,
                    trade_date,
                    bar_ts,
                    target_interval,
                    open_,
                    high,
                    low,
                    close,
                    int(volume or 0),
                )
            )
        if upsert_rows:
            self.db_client.execute_many(UPSERT_SQL, upsert_rows)
        return len(upsert_rows)

    def compact_ladder(
        self,
        ticker: str,
        on_detail: Optional[Callable[[str], None]] = None,
    ) -> dict[str, int]:
        """Promote aged fine bars into coarser intervals, then delete expired fines."""
        stats: dict[str, int] = {}
        now = datetime.now(timezone.utc)
        for source, target in COMPACTION_STEPS:
            keep_days = BANDS[source]["keep_days"]
            if keep_days is None:
                continue
            if on_detail:
                on_detail(f"{ticker} · compact aged {source} → {target}")
            cutoff = now - timedelta(days=keep_days)
            promoted = self._aggregate_aged_bars(ticker, source, target, cutoff)
            self.db_client.execute_query(
                """
                DELETE FROM stock_data
                WHERE ticker = %s
                  AND bar_interval = %s
                  AND bar_ts < %s
                """,
                (ticker, source, cutoff),
            )
            stats[f"promoted_{source}_to_{target}"] = promoted

        if on_detail:
            on_detail(f"{ticker} · compact cleanup (dedupe daily)")
        # Dedupe accidental duplicate 1d rows for same calendar day
        self.db_client.execute_query(
            """
            DELETE FROM stock_data a
            USING stock_data b
            WHERE a.ticker = %s
              AND b.ticker = %s
              AND a.bar_interval = '1d'
              AND b.bar_interval = '1d'
              AND a.date = b.date
              AND a.id < b.id
            """,
            (ticker, ticker),
        )
        logger.info(f"{ticker}: ladder compaction {stats}")
        return stats

    def migrate_legacy_5m(
        self,
        ticker: str,
        on_detail: Optional[Callable[[str], None]] = None,
    ) -> dict[str, int]:
        """One-time: aggregate legacy 5m → 15m/30m/1h (+ daily), then delete 5m."""
        rows, _ = self.db_client.fetch_query(
            """
            SELECT COUNT(*) FROM stock_data
            WHERE ticker = %s AND bar_interval = %s
            """,
            (ticker, BAR_5M_LEGACY),
        )
        count = int(rows[0][0]) if rows else 0
        if count == 0:
            return {"legacy_5m": 0}

        if on_detail:
            on_detail(f"{ticker} · migrate legacy 5m ({count} bars)")
        # Far-future cutoff so all 5m rows are aggregated
        far = datetime.now(timezone.utc) + timedelta(days=3650)
        to_15 = self._aggregate_aged_bars(ticker, BAR_5M_LEGACY, BAR_15M, far)
        to_30 = self._aggregate_aged_bars(ticker, BAR_5M_LEGACY, BAR_30M, far)
        to_1h = self._aggregate_aged_bars(ticker, BAR_5M_LEGACY, BAR_1H, far)
        to_1d = self._aggregate_aged_bars(ticker, BAR_5M_LEGACY, BAR_1D, far)

        self.db_client.execute_query(
            """
            DELETE FROM stock_data
            WHERE ticker = %s AND bar_interval = %s
            """,
            (ticker, BAR_5M_LEGACY),
        )
        logger.info(
            f"{ticker}: migrated {count} legacy 5m bars "
            f"(15m={to_15}, 30m={to_30}, 1h={to_1h}, 1d={to_1d})"
        )
        return {
            "legacy_5m": count,
            "migrated_15m": to_15,
            "migrated_30m": to_30,
            "migrated_1h": to_1h,
            "migrated_1d": to_1d,
        }

    def scrape_ticker(
        self,
        ticker: str,
        on_detail: Optional[Callable[[str], None]] = None,
    ) -> dict[str, Any]:
        ticker = ticker.upper().strip()
        if on_detail:
            on_detail(f"{ticker} · check legacy 5m migration")
        migrated = self.migrate_legacy_5m(ticker, on_detail=on_detail)
        counts: dict[str, int] = {}
        for interval in (BAR_1M, BAR_15M, BAR_30M, BAR_1H, BAR_1D):
            counts[interval] = self.sync_band(ticker, interval, on_detail=on_detail)
        if on_detail:
            on_detail(f"{ticker} · compact price ladder")
        compact = self.compact_ladder(ticker, on_detail=on_detail)
        if on_detail:
            on_detail(f"{ticker} · price sync complete")
        return {
            "ticker": ticker,
            "bands": counts,
            **migrated,
            **compact,
        }

    def scrape_all_tickers(
        self,
        tickers: list[str],
        on_progress: Optional[Callable[[str, int, int], None]] = None,
        on_ticker_done: Optional[Callable[[str], None]] = None,
        on_detail: Optional[Callable[[str], None]] = None,
        should_continue: Optional[Callable[[], bool]] = None,
    ) -> None:
        total = len(tickers)
        for index, ticker in enumerate(tickers, start=1):
            if should_continue is not None and not should_continue():
                logger.info("Price scrape stopped early (cancel requested)")
                return
            try:
                logger.info(f"Syncing prices for {ticker} ({index}/{total})...")
                if on_progress:
                    on_progress(ticker, index, total)
                result = self.scrape_ticker(ticker, on_detail=on_detail)
                logger.info(f"Price sync done for {ticker}: {result}")
                if on_ticker_done:
                    on_ticker_done(ticker)
            except Exception as exc:
                logger.error(f"Error syncing prices for {ticker}: {exc}")


if __name__ == "__main__":
    StockDataScraper().scrape_all_tickers(["AAPL", "MSFT"])
