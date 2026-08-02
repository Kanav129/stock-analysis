"""Migrate holdings_snapshot for IBKR Flex metadata columns."""
from __future__ import annotations

from db.db_factory import get_db_client
from utils.logger import logger

COLUMNS: list[tuple[str, str]] = [
    ("conid", "VARCHAR(32)"),
    ("asset_class", "VARCHAR(32)"),
    ("description", "TEXT"),
    ("exchange", "VARCHAR(64)"),
    ("side", "VARCHAR(16)"),
    ("multiplier", "DOUBLE PRECISION"),
    ("report_date", "VARCHAR(32)"),
    ("ibkr_mark_price", "DOUBLE PRECISION"),
    ("ibkr_position_value", "DOUBLE PRECISION"),
    ("cost_basis_money", "DOUBLE PRECISION"),
    ("cost_basis_price", "DOUBLE PRECISION"),
    ("ibkr_unrealized_pnl", "DOUBLE PRECISION"),
    ("percent_of_nav", "DOUBLE PRECISION"),
    ("fx_rate_to_base", "DOUBLE PRECISION"),
    ("raw_symbol", "VARCHAR(64)"),
    ("source", "VARCHAR(32) DEFAULT 'manual'"),
    ("source_data", "JSONB DEFAULT '{}'::jsonb"),
]


def migrate_holdings_schema() -> None:
    db = get_db_client()
    with db.checkout() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'holdings_snapshot'
                """
            )
            cols = {r[0] for r in cursor.fetchall()}
            if not cols:
                logger.info("holdings_snapshot missing — skip holdings migration.")
                return

            # Widen ticker for share-class symbols (BRK.B etc.)
            cursor.execute(
                "ALTER TABLE holdings_snapshot ALTER COLUMN ticker TYPE VARCHAR(32)"
            )
            cursor.execute(
                "ALTER TABLE holdings_snapshot ALTER COLUMN account_id TYPE VARCHAR(64)"
            )

            for name, typ in COLUMNS:
                if name not in cols:
                    cursor.execute(
                        f"ALTER TABLE holdings_snapshot ADD COLUMN {name} {typ}"
                    )

            conn.commit()
            logger.info("holdings_snapshot schema migration completed.")
        except Exception as exc:
            conn.rollback()
            logger.error(f"holdings_snapshot migration failed: {exc}")
            raise
        finally:
            cursor.close()
