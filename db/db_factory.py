import os

from dotenv import load_dotenv

from db.postgres_db import PostgresDBClient

load_dotenv()


def get_db_client() -> PostgresDBClient:
    return PostgresDBClient(
        host=os.getenv("POSTGRES_HOST"),
        database=os.getenv("POSTGRES_DB", "postgres"),
        user=os.getenv("POSTGRES_USERNAME", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD"),
        port=int(os.getenv("POSTGRES_PORT", 5432)),
        sslmode=os.getenv("POSTGRES_SSLMODE"),
    )
