from pathlib import Path

from db.db_factory import get_db_client
from db.migrate_ratings import migrate_stock_ratings_schema
from utils.logger import logger


def bootstrap_schema() -> None:
    schema_path = Path(__file__).parent / "schema.sql"
    sql = schema_path.read_text()
    db = get_db_client()
    db.connect()
    cursor = db.connection.cursor()
    try:
        cursor.execute(sql)
        db.connection.commit()
        logger.info("Database schema bootstrap completed.")
    except Exception as exc:
        db.connection.rollback()
        logger.error(f"Schema bootstrap failed: {exc}")
        raise
    finally:
        cursor.close()

    try:
        migrate_stock_ratings_schema()
    except Exception as exc:
        logger.error(f"Ratings migration skipped or failed: {exc}")
        raise
