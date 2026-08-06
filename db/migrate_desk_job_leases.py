"""Add worker_id / lease_until for multi-worker job ownership."""
from __future__ import annotations

from db.db_factory import get_db_client
from utils.logger import logger


def migrate_desk_job_leases() -> None:
    db = get_db_client()
    with db.checkout() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'desk_jobs'
                """
            )
            if not cur.fetchone():
                logger.info("desk_jobs missing — skip lease migration.")
                return

            cur.execute(
                """
                ALTER TABLE desk_jobs
                ADD COLUMN IF NOT EXISTS worker_id TEXT
                """
            )
            cur.execute(
                """
                ALTER TABLE desk_jobs
                ADD COLUMN IF NOT EXISTS lease_until TIMESTAMPTZ
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_desk_jobs_status_lease
                    ON desk_jobs (status, lease_until)
                """
            )
            conn.commit()
            logger.info("desk_jobs lease columns migration completed.")
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
