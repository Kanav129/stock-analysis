"""Ensure watchlist_suggestions table exists for AI idea desk."""
from __future__ import annotations

from db.db_factory import get_db_client
from utils.logger import logger


def migrate_watchlist_suggestions() -> None:
    db = get_db_client()
    with db.checkout() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS watchlist_suggestions (
                    ticker VARCHAR(10) PRIMARY KEY,
                    reason TEXT NOT NULL,
                    suggested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL,
                    source VARCHAR(16),
                    company_name TEXT,
                    company_blurb TEXT,
                    sector TEXT,
                    industry TEXT,
                    brief JSONB NOT NULL DEFAULT '{}'::jsonb
                )
                """
            )
            for stmt in (
                "ALTER TABLE watchlist_suggestions ADD COLUMN IF NOT EXISTS company_name TEXT",
                "ALTER TABLE watchlist_suggestions ADD COLUMN IF NOT EXISTS company_blurb TEXT",
                "ALTER TABLE watchlist_suggestions ADD COLUMN IF NOT EXISTS sector TEXT",
                "ALTER TABLE watchlist_suggestions ADD COLUMN IF NOT EXISTS industry TEXT",
                "ALTER TABLE watchlist_suggestions ADD COLUMN IF NOT EXISTS brief JSONB NOT NULL DEFAULT '{}'::jsonb",
            ):
                cur.execute(stmt)
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_watchlist_suggestions_expires
                    ON watchlist_suggestions (expires_at)
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_watchlist_suggestions_suggested
                    ON watchlist_suggestions (suggested_at DESC)
                """
            )
            conn.commit()
            logger.info("watchlist_suggestions migration completed.")
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
