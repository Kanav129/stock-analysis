"""Price sync: multi-resolution ladder for smooth charts.

Intervals kept (after compaction):
  1m  ~2d   → chart 1D
  15m ~8d   → chart 7D
  30m ~16d  → chart 2W
  1h  ~35d  → chart 1M
  1d  forever → chart 3M+

Daily sync delta-fetches each band from Yahoo (from last bar − overlap),
bulk-upserts with execute_values, then compacts aged fine bars into coarser
intervals. Legacy ``5m`` rows are migrated once then deleted.
"""

from __future__ import annotations

import os
import time
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

UPSERT_PAGE_SIZE = 500

# Snap bar timestamps to interval grids (seconds).
SNAP_SEC = {
    BAR_1M: 60,
    BAR_15M: 900,
    BAR_30M: 1800,
    BAR_1H: 3600,
}

# Retention windows + Yahoo policy. Delta sync uses overlap/skip; long_period
# is the cold-start / stale backfill window.
BANDS: dict[str, dict[str, Any]] = {
    BAR_1M: {
        "keep_days": 2,
        "fresh_age": timedelta(hours=36),
        "overlap": timedelta(hours=2),
        "skip_age": timedelta(minutes=3),
        "short_period": "2d",
        "long_period": "7d",
    },
    BAR_15M: {
        "keep_days": 8,
        "fresh_age": timedelta(days=3),
        "overlap": timedelta(days=1),
        "skip_age": timedelta(minutes=12),
        "short_period": "5d",
        "long_period": "1mo",
    },
    BAR_30M: {
        "keep_days": 16,
        "fresh_age": timedelta(days=4),
        "overlap": timedelta(days=1),
        "skip_age": timedelta(minutes=25),
        "short_period": "5d",
        "long_period": "1mo",
    },
    BAR_1H: {
        "keep_days": 35,
        "fresh_age": timedelta(days=4),
        "overlap": timedelta(days=1),
        "skip_age": timedelta(minutes=50),
        "short_period": "5d",
        "long_period": "1mo",
    },
    BAR_1D: {
        "keep_days": None,
        "fresh_age": timedelta(days=4),
        "overlap": timedelta(days=5),
        "skip_age": timedelta(hours=12),
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

# Multi-row VALUES template for psycopg2.extras.execute_values.
UPSERT_SQL = """
INSERT INTO stock_data (ticker, date, bar_ts, bar_interval, open, high, low, close, volume)
VALUES %s
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


def _fmt_age(age: timedelta) -> str:
    secs = int(age.total_seconds())
    if secs < 120:
        return f"{secs}s"
    mins = secs // 60
    if mins < 120:
        return f"{mins}m"
    hours = mins // 60
    return f"{hours}h"


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

    def fetch_history(
        self,
        ticker: str,
        interval: str,
        *,
        period: Optional[str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> pd.DataFrame:
        ticker_data = yf.Ticker(ticker)
        kwargs: dict[str, Any] = {"interval": interval, "auto_adjust": False}
        if start is not None:
            kwargs["start"] = start
            if end is not None:
                kwargs["end"] = end
        elif period is not None:
            kwargs["period"] = period
        else:
            raise ValueError("fetch_history requires period= or start=")
        return ticker_data.history(**kwargs)

    def _frame_to_rows(self, ticker: str, frame: pd.DataFrame, interval: str) -> list[tuple]:
        """Convert an OHLCV frame to upsert tuples (vectorized; no iterrows)."""
        if frame is None or frame.empty:
            return []
        cols = {c.lower(): c for c in frame.columns}
        for need in ("open", "high", "low", "close", "volume"):
            if need not in cols:
                return []
        opens = frame[cols["open"]].to_numpy()
        highs = frame[cols["high"]].to_numpy()
        lows = frame[cols["low"]].to_numpy()
        closes = frame[cols["close"]].to_numpy()
        volumes = frame[cols["volume"]].to_numpy()
        rows: list[tuple] = []
        for i, idx in enumerate(frame.index):
            if interval == BAR_1D:
                bar_ts = _daily_bar_ts(idx)
            else:
                bar_ts = _snap_ts(_as_utc_ts(idx), interval)
            trade_date = bar_ts.astimezone(timezone.utc).date()
            rows.append(
                (
                    ticker,
                    trade_date,
                    bar_ts,
                    interval,
                    _to_python(opens[i]),
                    _to_python(highs[i]),
                    _to_python(lows[i]),
                    _to_python(closes[i]),
                    int(_to_python(volumes[i]) or 0),
                )
            )
        return rows

    def upsert_daily_frame(self, ticker: str, frame: pd.DataFrame) -> int:
        rows = self._frame_to_rows(ticker, frame, BAR_1D)
        if not rows:
            return 0
        return self.db_client.execute_values(UPSERT_SQL, rows, page_size=UPSERT_PAGE_SIZE)

    def upsert_interval_frame(self, ticker: str, frame: pd.DataFrame, interval: str) -> int:
        """Upsert OHLCV bars (bulk execute_values)."""
        if interval == BAR_1D:
            return self.upsert_daily_frame(ticker, frame)
        rows = self._frame_to_rows(ticker, frame, interval)
        if not rows:
            return 0
        return self.db_client.execute_values(UPSERT_SQL, rows, page_size=UPSERT_PAGE_SIZE)

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
        return latest.astimezone(timezone.utc)

    def _fetch_period_for_band(self, ticker: str, interval: str) -> str:
        """Cold/stale period choice (used when delta is not applicable)."""
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
        """Delta gap-fill one resolution band from Yahoo, then bulk upsert."""
        cfg = BANDS[interval]
        latest = self._latest_bar_ts(ticker, interval)
        now = datetime.now(timezone.utc)

        if latest is not None:
            age = now - latest
            if age <= cfg["skip_age"]:
                if on_detail:
                    on_detail(f"{ticker} · skip {interval} · fresh ({_fmt_age(age)})")
                logger.info(f"{ticker}: skip {interval} (age={age})")
                return 0

        t0 = time.monotonic()
        if latest is None:
            period = cfg["long_period"]
            mode = f"backfill ({period})"
            if on_detail:
                on_detail(f"{ticker} · fetch {interval} · {mode}")
            frame = self.fetch_history(ticker, interval=interval, period=period)
            if frame is None or frame.empty:
                if on_detail:
                    on_detail(
                        f"{ticker} · fetch {interval} · retry short "
                        f"({cfg['short_period']})"
                    )
                frame = self.fetch_history(
                    ticker, interval=interval, period=cfg["short_period"]
                )
                mode = f"backfill ({cfg['short_period']})"
        elif now - latest > cfg["fresh_age"]:
            # Stale: full long window, then resume deltas next run.
            period = cfg["long_period"]
            mode = f"stale-backfill ({period})"
            if on_detail:
                on_detail(f"{ticker} · fetch {interval} · {mode}")
            frame = self.fetch_history(ticker, interval=interval, period=period)
            if frame is None or frame.empty:
                start = latest - cfg["overlap"]
                mode = f"delta since {start.isoformat()}"
                if on_detail:
                    on_detail(f"{ticker} · fetch {interval} · retry delta")
                frame = self.fetch_history(ticker, interval=interval, start=start)
        else:
            start = latest - cfg["overlap"]
            mode = f"delta since {start.strftime('%Y-%m-%d %H:%M')}Z"
            if on_detail:
                on_detail(f"{ticker} · fetch {interval} · {mode}")
            frame = self.fetch_history(ticker, interval=interval, start=start)
            if frame is None or frame.empty:
                # Yahoo sometimes returns empty for start=; fall back to short period.
                if on_detail:
                    on_detail(
                        f"{ticker} · fetch {interval} · retry short "
                        f"({cfg['short_period']})"
                    )
                frame = self.fetch_history(
                    ticker, interval=interval, period=cfg["short_period"]
                )
                mode = f"refresh ({cfg['short_period']})"

        fetch_ms = int((time.monotonic() - t0) * 1000)
        n_src = 0 if frame is None or frame.empty else len(frame)
        if on_detail:
            on_detail(
                f"{ticker} · upsert {interval} · {n_src} bar(s) from Yahoo "
                f"({fetch_ms}ms)…"
            )
        t1 = time.monotonic()
        n = self.upsert_interval_frame(ticker, frame, interval)
        upsert_ms = int((time.monotonic() - t1) * 1000)
        logger.info(
            f"{ticker}: upserted {n} {interval} bar(s) ({mode}; "
            f"fetch={fetch_ms}ms upsert={upsert_ms}ms)"
        )
        if on_detail:
            on_detail(
                f"{ticker} · {interval} done · {n} bar(s) · {mode} "
                f"(upsert {upsert_ms}ms)"
            )
        return n

    def refresh_live_1m(self, ticker: str) -> int:
        """Light intraday backfill: delta from last 1m bar, else today/2d."""
        ticker = ticker.upper().strip()
        cfg = BANDS[BAR_1M]
        latest = self._latest_bar_ts(ticker, BAR_1M)
        if latest is not None:
            start = latest - cfg["overlap"]
            frame = self.fetch_history(ticker, interval=BAR_1M, start=start)
        else:
            frame = self.fetch_history(ticker, interval=BAR_1M, period="1d")
            if frame is None or frame.empty:
                frame = self.fetch_history(ticker, interval=BAR_1M, period="2d")
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
                self.db_client.execute_values(
                    UPSERT_SQL, upsert_rows, page_size=UPSERT_PAGE_SIZE
                )
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
            self.db_client.execute_values(
                UPSERT_SQL, upsert_rows, page_size=UPSERT_PAGE_SIZE
            )
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
