from pathlib import Path
from unittest.mock import MagicMock, patch

from db.migrate_rls_error_tables import RLS_TABLES, migrate_rls_error_tables

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema.sql"


def _render_sql(stmt) -> str:
    chunks = []
    for part in stmt:
        wrapped = part._wrapped
        if isinstance(wrapped, str):
            chunks.append(wrapped)
        else:
            chunks.append("".join(wrapped))
    return "".join(chunks)


INFO_TABLES = (
    "app_settings",
    "holdings_snapshot",
    "stock_ratings",
    "stock_reports",
    "watchlist",
)


def _checkout(mock_get_db, conn):
    mock_get_db.return_value.checkout.return_value.__enter__ = MagicMock(return_value=conn)
    mock_get_db.return_value.checkout.return_value.__exit__ = MagicMock(return_value=False)


def test_schema_enables_rls_on_error_tables_only():
    schema = SCHEMA_PATH.read_text()
    for name in RLS_TABLES:
        create_at = schema.index(f"CREATE TABLE IF NOT EXISTS {name} ")
        alter_at = schema.index(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY;")
        assert create_at < alter_at
    for name in INFO_TABLES:
        assert f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY;" not in schema
    assert "CREATE POLICY" not in schema.upper()
    assert "REVOKE" not in schema.upper()


def test_rls_tables_are_the_six_error_tables():
    assert RLS_TABLES == (
        "desk_jobs",
        "llm_usage",
        "rating_outcomes",
        "watchlist_suggestions",
        "av_fundamentals",
        "analysis_calibration_snapshots",
    )


@patch("db.migrate_rls_error_tables.get_db_client")
def test_migrate_enables_only_tables_missing_rls(mock_get_db):
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchall.return_value = [("llm_usage",), ("watchlist",), ("desk_jobs",)]
    _checkout(mock_get_db, conn)

    migrate_rls_error_tables()

    executed = [c.args[0] for c in cur.execute.call_args_list]
    assert "relrowsecurity" in executed[0]
    assert cur.execute.call_args_list[0].args[1] == (list(RLS_TABLES),)
    rendered = [_render_sql(stmt) for stmt in executed[1:]]
    assert rendered == [
        "ALTER TABLE desk_jobs ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE llm_usage ENABLE ROW LEVEL SECURITY",
    ]
    assert all("POLICY" not in stmt for stmt in rendered)
    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()
    cur.close.assert_called_once()


@patch("db.migrate_rls_error_tables.get_db_client")
def test_migrate_is_noop_when_rls_already_enabled(mock_get_db):
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchall.return_value = []
    _checkout(mock_get_db, conn)

    migrate_rls_error_tables()

    assert cur.execute.call_count == 1
    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()


@patch("db.migrate_rls_error_tables.get_db_client")
def test_migrate_rolls_back_on_error(mock_get_db):
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.execute.side_effect = RuntimeError("boom")
    _checkout(mock_get_db, conn)

    try:
        migrate_rls_error_tables()
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError")

    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
    cur.close.assert_called_once()
