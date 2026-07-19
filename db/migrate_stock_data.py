"""Migrate stock_data to bar_ts + bar_interval with a uniqueness guarantee."""

from __future__ import annotations

from db.db_factory import get_db_client
from utils.logger import logger

DETAILED_WINDOW_DAYS = 30


def migrate_stock_data_schema() -> None:
    db = get_db_client()
    db.connect()
    cursor = db.connection.cursor()
    try:
        cursor.execute(
            """
            ALTER TABLE stock_data
                ADD COLUMN IF NOT EXISTS bar_ts TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS bar_interval VARCHAR(8) DEFAULT '1d'
            """
        )

        # Legacy rows: treat date as a daily bar at UTC midnight
        cursor.execute(
            """
            UPDATE stock_data
            SET bar_ts = date::timestamptz,
                bar_interval = COALESCE(NULLIF(TRIM(bar_interval), ''), '1d')
            WHERE bar_ts IS NULL AND date IS NOT NULL
            """
        )

        # Drop exact duplicates (same ticker + ts + interval), keep highest id
        cursor.execute(
            """
            DELETE FROM stock_data a
            USING stock_data b
            WHERE a.id < b.id
              AND a.ticker = b.ticker
              AND a.bar_ts IS NOT NULL
              AND b.bar_ts IS NOT NULL
              AND a.bar_ts = b.bar_ts
              AND COALESCE(a.bar_interval, '1d') = COALESCE(b.bar_interval, '1d')
            """
        )

        # Also collapse legacy daily duplicates that share the same calendar date
        cursor.execute(
            """
            DELETE FROM stock_data a
            USING stock_data b
            WHERE a.id < b.id
              AND a.ticker = b.ticker
              AND COALESCE(a.bar_interval, '1d') = '1d'
              AND COALESCE(b.bar_interval, '1d') = '1d'
              AND a.date IS NOT NULL
              AND b.date IS NOT NULL
              AND a.date = b.date
            """
        )

        cursor.execute(
            """
            UPDATE stock_data
            SET date = (bar_ts AT TIME ZONE 'UTC')::date
            WHERE bar_ts IS NOT NULL
              AND (date IS NULL OR date <> (bar_ts AT TIME ZONE 'UTC')::date)
            """
        )

        cursor.execute("ALTER TABLE stock_data ALTER COLUMN bar_ts SET NOT NULL")
        cursor.execute(
            "ALTER TABLE stock_data ALTER COLUMN bar_interval SET NOT NULL"
        )
        cursor.execute(
            "ALTER TABLE stock_data ALTER COLUMN bar_interval SET DEFAULT '1d'"
        )

        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_stock_data_ticker_ts_interval
            ON stock_data (ticker, bar_ts, bar_interval)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_stock_data_ticker_ts
            ON stock_data (ticker, bar_ts DESC)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_stock_data_ticker_interval_ts
            ON stock_data (ticker, bar_interval, bar_ts DESC)
            """
        )

        db.connection.commit()
        logger.info("stock_data schema migration completed (unique ticker/ts/interval).")
    except Exception as exc:
        db.connection.rollback()
        logger.error(f"stock_data schema migration failed: {exc}")
        raise
    finally:
        cursor.close()
