from unittest.mock import MagicMock, patch

from db.migrate_analysis_failure_flags import RATING_CHECK, migrate_analysis_failure_flags


def test_rating_check_allows_null():
    assert "rating IS NULL OR rating IN" in RATING_CHECK


@patch("db.migrate_analysis_failure_flags.get_db_client")
def test_migrate_skips_when_stock_ratings_missing(mock_get_db):
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchone.return_value = None
    mock_get_db.return_value.checkout.return_value.__enter__ = MagicMock(return_value=conn)
    mock_get_db.return_value.checkout.return_value.__exit__ = MagicMock(return_value=False)

    migrate_analysis_failure_flags()

    cur.execute.assert_called_once()
    conn.commit.assert_not_called()


@patch("db.migrate_analysis_failure_flags.get_db_client")
def test_migrate_adds_columns_relaxes_constraints_and_cleans_polluted_rows(mock_get_db):
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchone.side_effect = [(1,), None]
    cur.fetchall.return_value = [("stock_ratings_rating_check",)]
    mock_get_db.return_value.checkout.return_value.__enter__ = MagicMock(return_value=conn)
    mock_get_db.return_value.checkout.return_value.__exit__ = MagicMock(return_value=False)

    migrate_analysis_failure_flags()

    executed = [c.args[0].strip() for c in cur.execute.call_args_list]
    assert any("ADD COLUMN IF NOT EXISTS decision_ok" in sql for sql in executed)
    assert any("ADD COLUMN IF NOT EXISTS error_message" in sql for sql in executed)
    assert any("ALTER COLUMN rating DROP NOT NULL" in sql for sql in executed)
    assert any("ALTER COLUMN score DROP NOT NULL" in sql for sql in executed)
    assert any("DROP CONSTRAINT IF EXISTS" in sql for sql in executed)
    assert any(
        f"ADD CONSTRAINT stock_ratings_rating_check CHECK ({RATING_CHECK})" in sql
        for sql in executed
    )
    assert any("Decision generation failed" in sql for sql in executed)
    conn.commit.assert_called_once()
    cur.close.assert_called_once()


@patch("db.migrate_analysis_failure_flags.get_db_client")
def test_migrate_rolls_back_on_error(mock_get_db):
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchone.return_value = (1,)
    cur.execute.side_effect = [None, RuntimeError("boom")]
    mock_get_db.return_value.checkout.return_value.__enter__ = MagicMock(return_value=conn)
    mock_get_db.return_value.checkout.return_value.__exit__ = MagicMock(return_value=False)

    try:
        migrate_analysis_failure_flags()
    except RuntimeError:
        pass

    conn.rollback.assert_called_once()
    cur.close.assert_called_once()
