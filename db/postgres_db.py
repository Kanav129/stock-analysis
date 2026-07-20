import os
import threading

import psycopg2
from psycopg2 import OperationalError, sql
from utils.logger import logger


class PostgresDBClient:
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
            self.connection = None
            self._lock = threading.RLock()
            self._initialized = True

    def connect(self):
        """Establish a database connection."""
        if not self.connection or self.connection.closed:
            try:
                connect_kwargs = {
                    "host": self.host,
                    "database": self.database,
                    "user": self.user,
                    "password": self.password,
                    "port": self.port,
                    "connect_timeout": int(os.getenv("POSTGRES_CONNECT_TIMEOUT", "30")),
                }
                if self.sslmode:
                    connect_kwargs["sslmode"] = self.sslmode
                self.connection = psycopg2.connect(**connect_kwargs)
                # Bound stuck queries so scrapers cannot hang a free dyno forever.
                self.connection.set_session(autocommit=False)
                timeout_ms = os.getenv("POSTGRES_STATEMENT_TIMEOUT", "120000")
                try:
                    with self.connection.cursor() as cursor:
                        cursor.execute("SET statement_timeout = %s", (timeout_ms,))
                    self.connection.commit()
                except Exception as exc:
                    logger.warning(f"Could not set statement_timeout={timeout_ms}: {exc}")
                    if self.connection:
                        self.connection.rollback()
                logger.info("PostgreSQL connection established.")
            except OperationalError as e:
                logger.error(f"Error connecting to PostgreSQL: {e}")
                raise

    def close(self):
        """Close the database connection."""
        with self._lock:
            if self.connection:
                self.connection.close()
                self.connection = None
                logger.info("PostgreSQL connection closed.")

    def execute_query(self, query, params=None):
        """Execute a query (INSERT, UPDATE, DELETE)."""
        with self._lock:
            try:
                self.connect()
                cursor = self.connection.cursor()
                cursor.execute(query, params)
                self.connection.commit()
                cursor.close()
            except Exception as e:
                logger.error(f"Error executing query: {e}")
                if self.connection:
                    self.connection.rollback()
                raise

    def execute_many(self, query, params_seq):
        """Execute one parameterized statement for many rows in a single commit."""
        rows = list(params_seq or [])
        if not rows:
            return 0
        with self._lock:
            try:
                self.connect()
                cursor = self.connection.cursor()
                cursor.executemany(query, rows)
                self.connection.commit()
                cursor.close()
                return len(rows)
            except Exception as e:
                logger.error(f"Error executing batch query: {e}")
                if self.connection:
                    self.connection.rollback()
                raise

    def fetch_query(self, query, params=None):
        """Execute a SELECT query and fetch results."""
        with self._lock:
            try:
                self.connect()
                cursor = self.connection.cursor()
                cursor.execute(query, params)
                results = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                cursor.close()
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
