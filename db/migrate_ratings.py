"""Migrate stock_ratings from confidence 0–100 / 3-way tags to score −100…+100 / 7 tags."""
from __future__ import annotations

from db.db_factory import get_db_client
from utils.logger import logger

RATING_CHECK = (
    "rating IN ("
    "'STRONG_SELL', 'SELL', 'REDUCE', 'HOLD', 'ACCUMULATE', 'BUY', 'STRONG_BUY'"
    ")"
)


def migrate_stock_ratings_schema() -> None:
    db = get_db_client()
    with db.checkout() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'stock_ratings'
                """
            )
            cols = {r[0] for r in cursor.fetchall()}
            if not cols:
                logger.info("stock_ratings missing — skip rating migration.")
                return

            # Widen rating column
            cursor.execute("ALTER TABLE stock_ratings ALTER COLUMN rating TYPE VARCHAR(16)")

            # Drop old check constraints (names vary)
            cursor.execute(
                """
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'stock_ratings'::regclass AND contype = 'c'
                """
            )
            for (name,) in cursor.fetchall():
                cursor.execute(f'ALTER TABLE stock_ratings DROP CONSTRAINT IF EXISTS "{name}"')

            if "confidence" in cols and "score" not in cols:
                cursor.execute("ALTER TABLE stock_ratings RENAME COLUMN confidence TO score")
                # Legacy % values are not meaningful on −100…+100; zero until rescore
                cursor.execute(
                    """
                    UPDATE stock_ratings SET score = CASE
                        WHEN rating = 'BUY' THEN LEAST(70, GREATEST(20, score - 20))
                        WHEN rating = 'SELL' THEN -LEAST(70, GREATEST(20, score - 20))
                        ELSE LEAST(15, GREATEST(-15, score - 50))
                    END
                    """
                )
                logger.info("Renamed stock_ratings.confidence → score and remapped legacy values.")
            elif "score" not in cols:
                cursor.execute(
                    "ALTER TABLE stock_ratings ADD COLUMN score INTEGER NOT NULL DEFAULT 0"
                )

            cursor.execute(
                f"ALTER TABLE stock_ratings ADD CONSTRAINT stock_ratings_rating_check CHECK ({RATING_CHECK})"
            )
            cursor.execute(
                "ALTER TABLE stock_ratings ADD CONSTRAINT stock_ratings_score_check "
                "CHECK (score >= -100 AND score <= 100)"
            )

            # Refresh column set after possible renames/adds above
            cursor.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'stock_ratings'
                """
            )
            cols = {r[0] for r in cursor.fetchall()}
            if "report_type" not in cols:
                cursor.execute(
                    "ALTER TABLE stock_ratings ADD COLUMN report_type VARCHAR(16)"
                )
                # Best-effort backfill from nearby stock_reports rows
                cursor.execute(
                    """
                    UPDATE stock_ratings sr
                    SET report_type = matched.report_type
                    FROM (
                        SELECT sr2.id, rpt.report_type
                        FROM stock_ratings sr2
                        INNER JOIN LATERAL (
                            SELECT r.report_type
                            FROM stock_reports r
                            WHERE r.ticker = sr2.ticker
                              AND r.rating IS NOT NULL
                              AND r.created_at BETWEEN sr2.created_at - INTERVAL '15 minutes'
                                                  AND sr2.created_at + INTERVAL '15 minutes'
                            ORDER BY ABS(EXTRACT(EPOCH FROM (r.created_at - sr2.created_at)))
                            LIMIT 1
                        ) rpt ON TRUE
                        WHERE sr2.report_type IS NULL
                    ) matched
                    WHERE sr.id = matched.id
                    """
                )
                logger.info("Added stock_ratings.report_type and backfilled from reports.")

            cursor.execute(
                "ALTER TABLE stock_ratings DROP CONSTRAINT IF EXISTS stock_ratings_report_type_check"
            )
            cursor.execute(
                """
                ALTER TABLE stock_ratings
                ADD CONSTRAINT stock_ratings_report_type_check
                CHECK (report_type IS NULL OR report_type IN ('core', 'deep'))
                """
            )

            conn.commit()
            logger.info("stock_ratings schema migration completed.")
        except Exception as exc:
            conn.rollback()
            logger.error(f"stock_ratings migration failed: {exc}")
            raise
        finally:
            cursor.close()
