from unittest.mock import MagicMock, patch

from db.postgres_db import PostgresDBClient


def _client_with_mock_conn(connection):
    PostgresDBClient._instance = None
    client = PostgresDBClient("h", "d", "u", "p")
    PostgresDBClient._instance = None
    pool = MagicMock()
    pool.closed = False
    pool.getconn.return_value = connection
    client._pool = pool
    return client, pool


def test_execute_many_uses_executemany_and_single_commit():
    connection = MagicMock()
    cursor = MagicMock()
    connection.cursor.return_value = cursor
    connection.closed = False
    client, pool = _client_with_mock_conn(connection)

    n = client.execute_many("INSERT INTO t VALUES (%s)", [("a",), ("b",), ("c",)])

    assert n == 3
    cursor.executemany.assert_called_once()
    connection.commit.assert_called()
    assert cursor.execute.call_count == 0
    pool.putconn.assert_called()


def test_execute_many_noop_on_empty():
    connection = MagicMock()
    connection.closed = False
    client, pool = _client_with_mock_conn(connection)

    assert client.execute_many("INSERT INTO t VALUES (%s)", []) == 0
    connection.cursor.assert_not_called()
    pool.getconn.assert_not_called()


@patch("db.postgres_db.execute_values")
def test_execute_values_batches_and_commits(mock_ev):
    connection = MagicMock()
    cursor = MagicMock()
    connection.cursor.return_value = cursor
    connection.closed = False
    client, pool = _client_with_mock_conn(connection)

    sql = "INSERT INTO t (a) VALUES %s ON CONFLICT DO NOTHING"
    rows = [("a",), ("b",), ("c",)]
    n = client.execute_values(sql, rows, page_size=500)

    assert n == 3
    mock_ev.assert_called_once()
    assert mock_ev.call_args.args[0] is cursor
    assert mock_ev.call_args.args[1] == sql
    assert mock_ev.call_args.args[2] == rows
    assert mock_ev.call_args.kwargs["page_size"] == 500
    connection.commit.assert_called()
    pool.putconn.assert_called()


def test_execute_values_noop_on_empty():
    connection = MagicMock()
    connection.closed = False
    client, _pool = _client_with_mock_conn(connection)

    assert client.execute_values("INSERT INTO t VALUES %s", []) == 0
    connection.cursor.assert_not_called()


def test_fetch_query_returns_connection_to_pool():
    connection = MagicMock()
    cursor = MagicMock()
    cursor.fetchall.return_value = [("a",)]
    cursor.description = [("col",)]
    connection.cursor.return_value = cursor
    connection.closed = False
    client, pool = _client_with_mock_conn(connection)

    rows, cols = client.fetch_query("SELECT 1")
    assert rows == [("a",)]
    assert cols == ["col"]
    pool.putconn.assert_called_once_with(connection, close=False)
