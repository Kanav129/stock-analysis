from unittest.mock import MagicMock, patch

from db.postgres_db import PostgresDBClient


def test_execute_many_uses_executemany_and_single_commit():
    # Reset singleton so test gets a clean client
    PostgresDBClient._instance = None
    client = PostgresDBClient("h", "d", "u", "p")
    PostgresDBClient._instance = None

    connection = MagicMock()
    cursor = MagicMock()
    connection.cursor.return_value = cursor
    connection.closed = False
    client.connection = connection

    n = client.execute_many("INSERT INTO t VALUES (%s)", [("a",), ("b",), ("c",)])

    assert n == 3
    cursor.executemany.assert_called_once()
    connection.commit.assert_called()
    assert cursor.execute.call_count == 0


def test_execute_many_noop_on_empty():
    PostgresDBClient._instance = None
    client = PostgresDBClient("h", "d", "u", "p")
    PostgresDBClient._instance = None
    client.connection = MagicMock()

    assert client.execute_many("INSERT INTO t VALUES (%s)", []) == 0
    client.connection.cursor.assert_not_called()
