"""OutcomeService.refresh upserts from mocked ratings + bars."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from services.outcome_service import OutcomeService


@patch.object(OutcomeService, "refresh_calibration_snapshots", return_value=2)
def test_refresh_upserts_partial_outcome(mock_snaps):
    svc = OutcomeService()
    rated = datetime(2024, 1, 2, 15, 0, tzinfo=timezone.utc)
    closes = [
        (datetime(2024, 1, 2, tzinfo=timezone.utc), 100.0),
        (datetime(2024, 1, 3, tzinfo=timezone.utc), 101.0),
        (datetime(2024, 1, 4, tzinfo=timezone.utc), 102.0),
        (datetime(2024, 1, 5, tzinfo=timezone.utc), 103.0),
        (datetime(2024, 1, 8, tzinfo=timezone.utc), 104.0),
    ]
    svc._db = MagicMock()
    svc._load_candidate_ratings = MagicMock(
        return_value=[
            {
                "id": 7,
                "ticker": "AAPL",
                "rating": "BUY",
                "score": 45,
                "report_type": "deep",
                "price_summary": {"live_price": 100.0},
                "created_at": rated,
                "report_live_price": None,
            }
        ]
    )
    svc._load_daily_closes = MagicMock(return_value=closes)

    out = svc.refresh()
    assert out["updated"] == 1
    assert out["snapshots"] == 2
    assert svc._db.execute_query.called
    sql = svc._db.execute_query.call_args[0][0]
    assert "INSERT INTO rating_outcomes" in sql
    params = svc._db.execute_query.call_args[0][1]
    # return_5d = (104-100)/100 = 0.04; 20d not ready
    assert params[7] == 104.0  # price_5d
    assert abs(params[8] - 0.04) < 1e-9  # return_5d
    assert params[10] is None  # price_20d
    assert params[15] == "partial"


@patch.object(OutcomeService, "refresh_calibration_snapshots", return_value=0)
def test_refresh_skips_missing_entry_price(mock_snaps):
    svc = OutcomeService()
    svc._db = MagicMock()
    svc._load_candidate_ratings = MagicMock(
        return_value=[
            {
                "id": 8,
                "ticker": "MSFT",
                "rating": "HOLD",
                "score": 0,
                "report_type": "core",
                "price_summary": {},
                "created_at": datetime(2024, 1, 2, tzinfo=timezone.utc),
                "report_live_price": None,
            }
        ]
    )
    svc._load_daily_closes = MagicMock(return_value=[])

    out = svc.refresh()
    assert out["updated"] == 1
    params = svc._db.execute_query.call_args[0][1]
    assert params[6] is None  # entry_price
    assert params[15] == "skipped"
