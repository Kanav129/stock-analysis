from pathlib import Path

from db.db_factory import get_db_client
from db.migrate_ratings import migrate_stock_ratings_schema
from db.migrate_stock_data import migrate_stock_data_schema
from utils.logger import logger


def bootstrap_schema() -> None:
    schema_path = Path(__file__).parent / "schema.sql"
    sql = schema_path.read_text()
    db = get_db_client()
    with db.checkout() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(sql)
            conn.commit()
            logger.info("Database schema bootstrap completed.")
        except Exception as exc:
            conn.rollback()
            logger.error(f"Schema bootstrap failed: {exc}")
            raise
        finally:
            cursor.close()

    try:
        migrate_stock_ratings_schema()
    except Exception as exc:
        logger.error(f"Ratings migration skipped or failed: {exc}")
        raise

    try:
        migrate_stock_data_schema()
    except Exception as exc:
        logger.error(f"stock_data migration skipped or failed: {exc}")
        raise
