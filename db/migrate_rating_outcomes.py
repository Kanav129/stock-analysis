"""Ensure rating_outcomes + analysis_calibration_snapshots tables exist."""
from __future__ import annotations

from db.db_factory import get_db_client
from utils.logger import logger


def migrate_rating_outcomes() -> None:
    db = get_db_client()
    with db.checkout() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS rating_outcomes (
                    rating_id INTEGER PRIMARY KEY REFERENCES stock_ratings(id) ON DELETE CASCADE,
                    ticker VARCHAR(10) NOT NULL,
                    rated_at TIMESTAMPTZ NOT NULL,
                    rating VARCHAR(16),
                    score INTEGER,
                    report_type VARCHAR(16),
                    entry_price DOUBLE PRECISION,
                    price_5d DOUBLE PRECISION,
                    return_5d DOUBLE PRECISION,
                    ready_5d_at TIMESTAMPTZ,
                    price_20d DOUBLE PRECISION,
                    return_20d DOUBLE PRECISION,
                    ready_20d_at TIMESTAMPTZ,
                    direction_hit_5d BOOLEAN,
                    direction_hit_20d BOOLEAN,
                    status VARCHAR(16) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'partial', 'complete', 'skipped')),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rating_outcomes_ticker_rated
                    ON rating_outcomes (ticker, rated_at DESC)
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rating_outcomes_status
                    ON rating_outcomes (status)
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rating_outcomes_score
                    ON rating_outcomes (score)
                    WHERE score IS NOT NULL AND status IN ('partial', 'complete')
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_calibration_snapshots (
                    id SERIAL PRIMARY KEY,
                    as_of DATE NOT NULL,
                    horizon VARCHAR(8) NOT NULL CHECK (horizon IN ('5d', '20d')),
                    slice_key VARCHAR(128) NOT NULL,
                    n INTEGER NOT NULL DEFAULT 0,
                    hit_rate DOUBLE PRECISION,
                    avg_return DOUBLE PRECISION,
                    median_return DOUBLE PRECISION,
                    notes TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (as_of, horizon, slice_key)
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_calibration_snapshots_as_of
                    ON analysis_calibration_snapshots (as_of DESC, horizon)
                """
            )
            conn.commit()
            logger.info("rating_outcomes migration completed.")
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
