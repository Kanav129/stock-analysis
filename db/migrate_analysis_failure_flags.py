"""Add decision_ok / error_message; allow null rating/score on failed rows."""
from __future__ import annotations

from db.db_factory import get_db_client
from utils.logger import logger

RATING_CHECK = (
    "rating IS NULL OR rating IN ("
    "'STRONG_SELL','SELL','REDUCE','HOLD','ACCUMULATE','BUY','STRONG_BUY')"
)


def migrate_analysis_failure_flags() -> None:
    db = get_db_client()
    with db.checkout() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'stock_ratings'
                """
            )
            if not cur.fetchone():
                logger.info("stock_ratings missing — skip analysis failure migration.")
                return

            cur.execute(
                """
                ALTER TABLE stock_ratings
                ADD COLUMN IF NOT EXISTS decision_ok BOOLEAN NOT NULL DEFAULT TRUE
                """
            )
            cur.execute(
                """
                ALTER TABLE stock_ratings
                ADD COLUMN IF NOT EXISTS error_message TEXT
                """
            )
            cur.execute("ALTER TABLE stock_ratings ALTER COLUMN rating DROP NOT NULL")
            cur.execute("ALTER TABLE stock_ratings ALTER COLUMN score DROP NOT NULL")

            # Refresh rating check to allow NULL
            cur.execute(
                """
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'stock_ratings'::regclass AND contype = 'c'
                  AND pg_get_constraintdef(oid) ILIKE '%rating%'
                """
            )
            for (name,) in cur.fetchall():
                cur.execute(f'ALTER TABLE stock_ratings DROP CONSTRAINT IF EXISTS "{name}"')
            cur.execute(
                f"ALTER TABLE stock_ratings ADD CONSTRAINT stock_ratings_rating_check "
                f"CHECK ({RATING_CHECK})"
            )

            # Polluted soft-fail rows
            cur.execute(
                """
                UPDATE stock_ratings
                SET decision_ok = FALSE,
                    error_message = LEFT(reasoning, 500),
                    rating = NULL,
                    score = NULL
                WHERE decision_ok = TRUE
                  AND reasoning ILIKE '%Decision generation failed%'
                """
            )
            conn.commit()
            logger.info("Analysis failure flags migration completed.")
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
