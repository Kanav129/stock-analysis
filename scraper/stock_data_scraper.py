"""Price sync: daily closes forever + 5m bars for the last 30 days. Never duplicates."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

from db.postgres_db import PostgresDBClient
from utils.logger import logger

DETAILED_WINDOW_DAYS = 30
# If we already have 5m bars newer than this, only fetch a short window.
INCREMENTAL_MAX_AGE = timedelta(days=3)
BAR_1D = "1d"
BAR_5M = "5m"

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

    def _upsert_row(
        self,
        ticker: str,
        bar_ts: datetime,
        bar_interval: str,
        row: pd.Series,
    ) -> None:
        self.db_client.execute_query(
            UPSERT_SQL,
            self._row_params(ticker, bar_ts, bar_interval, row),
        )

    def upsert_daily_frame(self, ticker: str, frame: pd.DataFrame) -> int:
        if frame is None or frame.empty:
            return 0
        rows = [
            self._row_params(ticker, _daily_bar_ts(idx), BAR_1D, row)
            for idx, row in frame.iterrows()
        ]
        return self.db_client.execute_many(UPSERT_SQL, rows)

    def upsert_intraday_frame(self, ticker: str, frame: pd.DataFrame) -> int:
        if frame is None or frame.empty:
            return 0
        rows = []
        for idx, row in frame.iterrows():
            bar_ts = _as_utc_ts(idx)
            # Snap to 5-minute grid to avoid near-duplicate timestamps
            epoch = int(bar_ts.timestamp())
            snapped = epoch - (epoch % 300)
            bar_ts = datetime.fromtimestamp(snapped, tz=timezone.utc)
            rows.append(self._row_params(ticker, bar_ts, BAR_5M, row))
        return self.db_client.execute_many(UPSERT_SQL, rows)

    def backfill_missing_daily(self, ticker: str) -> int:
        """Pull ~1 month of daily bars and upsert (fills any missing days)."""
        frame = self.fetch_history(ticker, period="1mo", interval="1d")
        n = self.upsert_daily_frame(ticker, frame)
        logger.info(f"{ticker}: upserted {n} daily bar(s) from 1mo history")
        return n

    def _latest_intraday_ts(self, ticker: str) -> Optional[datetime]:
        rows, _ = self.db_client.fetch_query(
            """
            SELECT MAX(bar_ts) AS latest
            FROM stock_data
            WHERE ticker = %s AND bar_interval = %s
            """,
            (ticker, BAR_5M),
        )
        if not rows or rows[0][0] is None:
            return None
        latest = rows[0][0]
        if latest.tzinfo is None:
            return latest.replace(tzinfo=timezone.utc)
        return latest

    def _intraday_fetch_period(self, ticker: str) -> str:
        """Use a short window when we already have recent 5m data (daily cron)."""
        latest = self._latest_intraday_ts(ticker)
        if latest is None:
            return "1mo"
        age = datetime.now(timezone.utc) - latest
        if age <= INCREMENTAL_MAX_AGE:
            return "5d"
        return "1mo"

    def sync_intraday_5m(self, ticker: str) -> int:
        """
        Pull recent 5m bars and upsert.
        yfinance allows ~60d of 5m; we keep only the last 30d after compaction.
        Incremental runs fetch 5d when recent bars already exist.
        """
        period = self._intraday_fetch_period(ticker)
        frame = self.fetch_history(ticker, period=period, interval="5m")
        if (frame is None or frame.empty) and period != "5d":
            frame = self.fetch_history(ticker, period="5d", interval="5m")
        n = self.upsert_intraday_frame(ticker, frame)
        logger.info(f"{ticker}: upserted {n} 5m bar(s) (period={period})")
        return n

    def compact_old_intraday(self, ticker: str) -> dict[str, int]:
        """
        Older than 30 days: keep only one daily close; delete 5m bars.
        Ensures a 1d row exists (from last 5m close of that day if needed).
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=DETAILED_WINDOW_DAYS)

        # Materialize daily closes from aging 5m bars before deleting them
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
            (ticker, BAR_5M, cutoff),
        )

        promoted_rows = []
        for trade_date, open_, high, low, close, volume in rows:
            bar_ts = datetime(
                trade_date.year, trade_date.month, trade_date.day, tzinfo=timezone.utc
            )
            promoted_rows.append(
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
        if promoted_rows:
            self.db_client.execute_many(UPSERT_SQL, promoted_rows)
        promoted = len(promoted_rows)

        self.db_client.execute_query(
            """
            DELETE FROM stock_data
            WHERE ticker = %s
              AND bar_interval = %s
              AND bar_ts < %s
            """,
            (ticker, BAR_5M, cutoff),
        )

        # Safety: remove any accidental duplicate 1d rows for same calendar day
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

        logger.info(
            f"{ticker}: compacted 5m bars older than {DETAILED_WINDOW_DAYS}d "
            f"(promoted {promoted} daily close(s))"
        )
        return {"promoted_daily": promoted}

    def scrape_ticker(self, ticker: str) -> dict[str, Any]:
        ticker = ticker.upper().strip()
        daily_n = self.backfill_missing_daily(ticker)
        intraday_n = self.sync_intraday_5m(ticker)
        compact = self.compact_old_intraday(ticker)
        return {
            "ticker": ticker,
            "daily_upserted": daily_n,
            "intraday_upserted": intraday_n,
            **compact,
        }

    def scrape_all_tickers(
        self,
        tickers: list[str],
        on_progress: Optional[Callable[[str, int, int], None]] = None,
    ) -> None:
        total = len(tickers)
        for index, ticker in enumerate(tickers, start=1):
            try:
                logger.info(f"Syncing prices for {ticker} ({index}/{total})...")
                if on_progress:
                    on_progress(ticker, index, total)
                result = self.scrape_ticker(ticker)
                logger.info(f"Price sync done for {ticker}: {result}")
            except Exception as exc:
                logger.error(f"Error syncing prices for {ticker}: {exc}")


# Example usage
if __name__ == "__main__":
    StockDataScraper().scrape_all_tickers(["AAPL", "MSFT"])
