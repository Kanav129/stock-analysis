from unittest.mock import MagicMock, patch

from services.quotes_service import QuotesService


def test_get_quotes_uses_1d_spark_and_windowed_latest():
    db = MagicMock()
    db.fetch_query.side_effect = [
        # daily spark
        ([("AAPL", "2026-07-20", 100.0), ("AAPL", "2026-07-21", 102.0)], ["ticker", "trade_date", "close"]),
        # latest windowed
        ([("AAPL", 103.0, MagicMock(isoformat=lambda: "2026-07-21T20:00:00+00:00"), "1m")], None),
    ]

    with patch("services.quotes_service.get_db_client", return_value=db):
        out = QuotesService().get_quotes(["AAPL"], spark_days=30)

    assert out["AAPL"]["latest_close"] == 103.0
    assert out["AAPL"]["spark"] == [100.0, 102.0]
    spark_sql = db.fetch_query.call_args_list[0].args[0]
    latest_sql = db.fetch_query.call_args_list[1].args[0]
    assert "bar_interval = '1d'" in spark_sql
    assert "NOW() - INTERVAL '7 days'" in latest_sql
    assert "DISTINCT ON (ticker, date)" not in spark_sql
