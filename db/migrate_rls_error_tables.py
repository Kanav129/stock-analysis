"""Enable RLS on the six public tables that lacked it. No policies.

Production already has this applied. The script is idempotent: it enables RLS
only when the table exists and relrowsecurity is still false. Render connects
as postgres (BYPASSRLS); the SPA does not use PostgREST, so zero policies is
intentional and anon/authenticated stay denied.
"""
from __future__ import annotations

from psycopg2 import sql

from db.db_factory import get_db_client
from utils.logger import logger

# Advisor ERROR tables only. Tables that already had RLS stay untouched.
RLS_TABLES = (
    "desk_jobs",
    "llm_usage",
    "rating_outcomes",
    "watchlist_suggestions",
    "av_fundamentals",
    "analysis_calibration_snapshots",
)


def migrate_rls_error_tables() -> None:
    db = get_db_client()
    with db.checkout() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT c.relname
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relkind = 'r'
                  AND c.relname = ANY(%s)
                  AND NOT c.relrowsecurity
                """,
                (list(RLS_TABLES),),
            )
            pending = {row[0] for row in cur.fetchall()}
            enabled: list[str] = []
            for name in RLS_TABLES:
                if name not in pending:
                    continue
                cur.execute(
                    sql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(
                        sql.Identifier(name)
                    )
                )
                enabled.append(name)
            conn.commit()
            if enabled:
                logger.info("Enabled row level security on: " + ", ".join(enabled))
            else:
                logger.info("RLS already enabled on error tables (or tables missing).")
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
