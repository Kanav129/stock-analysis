import os
import threading
from contextlib import contextmanager
from typing import Iterator, Optional

from psycopg2 import OperationalError, sql
from psycopg2.extras import execute_values
from psycopg2.pool import ThreadedConnectionPool
from utils.logger import logger


class PostgresDBClient:
    """Thread-safe Postgres client backed by a small connection pool.

    Sync scrapers used to serialize the whole API behind one locked connection;
    desk reads hung for minutes while prices/news wrote. Pooling lets reads
    proceed on other connections while a scraper holds one.
    """

    _instance = None  # Singleton instance

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, host, database, user, password, port=5432, sslmode=None):
        if not hasattr(self, "_initialized"):
            self.host = host
            self.database = database
            self.user = user
            self.password = password
            self.port = port
            self.sslmode = sslmode or os.getenv("POSTGRES_SSLMODE")
            self._pool: Optional[ThreadedConnectionPool] = None
            self._pool_lock = threading.Lock()
            # Legacy attribute used by migration scripts via connect()/close()
            self.connection = None
            self._initialized = True

    def _connect_kwargs(self) -> dict:
        timeout_ms = os.getenv("POSTGRES_STATEMENT_TIMEOUT", "120000")
        kwargs = {
            "host": self.host,
            "database": self.database,
            "user": self.user,
            "password": self.password,
            "port": self.port,
            "connect_timeout": int(os.getenv("POSTGRES_CONNECT_TIMEOUT", "30")),
            "options": f"-c statement_timeout={timeout_ms}",
        }
        if self.sslmode:
            kwargs["sslmode"] = self.sslmode
        return kwargs

    def _ensure_pool(self) -> ThreadedConnectionPool:
        with self._pool_lock:
            if self._pool is not None and not self._pool.closed:
                return self._pool
            minconn = max(1, int(os.getenv("POSTGRES_POOL_MIN", "2")))
            # Desk polls + live-refresh + research share one process; 8 saturated easily.
            maxconn = max(minconn, int(os.getenv("POSTGRES_POOL_MAX", "16")))
            self._pool = ThreadedConnectionPool(minconn, maxconn, **self._connect_kwargs())
            logger.info(f"PostgreSQL pool ready (min={minconn}, max={maxconn}).")
            return self._pool

    def _putconn(self, conn, *, close: bool = False) -> None:
        pool = self._pool
        if pool is None:
            try:
                conn.close()
            except Exception:
                pass
            return
        try:
            pool.putconn(conn, close=close)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass

    @contextmanager
    def checkout(self) -> Iterator:
        """Borrow a connection from the pool for the duration of the block."""
        pool = self._ensure_pool()
        conn = pool.getconn()
        if conn.closed:
            self._putconn(conn, close=True)
            conn = pool.getconn()
        discard = False
        try:
            yield conn
        except OperationalError:
            discard = True
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            self._putconn(conn, close=discard)

    def connect(self):
        """Borrow one connection onto self.connection for migration scripts."""
        if self.connection and not getattr(self.connection, "closed", True):
            return
        pool = self._ensure_pool()
        self.connection = pool.getconn()
        logger.info("PostgreSQL connection established.")

    def close(self):
        """Return the migration connection (if any) and close the pool."""
        with self._pool_lock:
            if self.connection is not None:
                self._putconn(self.connection)
                self.connection = None
            if self._pool is not None and not self._pool.closed:
                self._pool.closeall()
                self._pool = None
                logger.info("PostgreSQL connection pool closed.")

    def execute_query(self, query, params=None):
        """Execute a query (INSERT, UPDATE, DELETE)."""
        with self.checkout() as conn:
            try:
                cursor = conn.cursor()
                cursor.execute(query, params)
                conn.commit()
                cursor.close()
            except Exception as e:
                logger.error(f"Error executing query: {e}")
                raise

    def execute_many(self, query, params_seq):
        """Execute one parameterized statement for many rows in a single commit."""
        rows = list(params_seq or [])
        if not rows:
            return 0
        with self.checkout() as conn:
            try:
                cursor = conn.cursor()
                cursor.executemany(query, rows)
                conn.commit()
                cursor.close()
                return len(rows)
            except Exception as e:
                logger.error(f"Error executing batch query: {e}")
                raise

    def execute_values(self, query, params_seq, *, page_size: int = 500):
        """Bulk INSERT/UPSERT via psycopg2 execute_values (multi-row VALUES pages).

        ``query`` must use a single ``VALUES %s`` placeholder (not per-column %s).
        """
        rows = list(params_seq or [])
        if not rows:
            return 0
        with self.checkout() as conn:
            try:
                cursor = conn.cursor()
                execute_values(cursor, query, rows, page_size=page_size)
                conn.commit()
                cursor.close()
                return len(rows)
            except Exception as e:
                logger.error(f"Error executing values batch: {e}")
                raise

    def fetch_query(self, query, params=None):
        """Execute a SELECT query and fetch results."""
        with self.checkout() as conn:
            try:
                cursor = conn.cursor()
                cursor.execute(query, params)
                results = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                cursor.close()
                conn.commit()
                return results, columns
            except Exception as e:
                logger.error(f"Error fetching data: {e}")
                raise

    # CRUD Methods
    def create(self, table, data):
        """Insert a row into a table."""
        try:
            columns = data.keys()
            values = tuple(data.values())
            query = sql.SQL(
                "INSERT INTO {table} ({fields}) VALUES ({placeholders})"
            ).format(
                table=sql.Identifier(table),
                fields=sql.SQL(", ").join(map(sql.Identifier, columns)),
                placeholders=sql.SQL(", ").join(sql.Placeholder() * len(columns)),
            )
            self.execute_query(query, values)
        except Exception as e:
            logger.error(f"Error in CREATE operation: {e}")
            raise

    def read(self, table, conditions=None):
        """Read rows from a table."""
        try:
            query = sql.SQL("SELECT * FROM {table}").format(
                table=sql.Identifier(table)
            )
            if conditions:
                condition_clause = sql.SQL(" WHERE {conditions}").format(
                    conditions=sql.SQL(" AND ").join(
                        [sql.SQL(f"{key} = %s") for key in conditions.keys()]
                    )
                )
                query += condition_clause
                params = tuple(conditions.values())
            else:
                params = None

            return self.fetch_query(query, params)
        except Exception as e:
            logger.error(f"Error in READ operation: {e}")
            raise

    def update(self, table, data, conditions):
        """Update rows in a table."""
        try:
            set_clause = sql.SQL(", ").join(
                [sql.SQL(f"{key} = %s") for key in data.keys()]
            )
            condition_clause = sql.SQL(" AND ").join(
                [sql.SQL(f"{key} = %s") for key in conditions.keys()]
            )
            query = sql.SQL(
                "UPDATE {table} SET {set_clause} WHERE {condition_clause}"
            ).format(
                table=sql.Identifier(table),
                set_clause=set_clause,
                condition_clause=condition_clause,
            )
            params = tuple(data.values()) + tuple(conditions.values())
            self.execute_query(query, params)
        except Exception as e:
            logger.error(f"Error in UPDATE operation: {e}")
            raise

    def delete(self, table, conditions):
        """Delete rows from a table."""
        try:
            condition_clause = sql.SQL(" AND ").join(
                [sql.SQL(f"{key} = %s") for key in conditions.keys()]
            )
            query = sql.SQL("DELETE FROM {table} WHERE {condition_clause}").format(
                table=sql.Identifier(table),
                condition_clause=condition_clause,
            )
            params = tuple(conditions.values())
            self.execute_query(query, params)
        except Exception as e:
            logger.error(f"Error in DELETE operation: {e}")
            raise
