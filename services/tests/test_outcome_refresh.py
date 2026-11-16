"""OutcomeService.refresh upserts from mocked ratings + bars."""
from datetime import date, datetime, timedelta, timezone
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
    svc._db.fetch_query.return_value = ([], [])
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
    svc._db.fetch_query.return_value = ([], [])
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


@patch.object(OutcomeService, "refresh_calibration_snapshots", return_value=1)
def test_refresh_scores_hold_against_each_horizon_band(mock_snaps):
    svc = OutcomeService()
    rated = datetime(2024, 1, 2, 15, 0, tzinfo=timezone.utc)
    # Bar 0 is the rating day. Day 5 close is +4% (hit). Day 20 close is +19% (miss).
    closes = [
        (rated.replace(hour=0) + timedelta(days=i), 100.0 + i)
        for i in range(25)
    ]
    svc._db = MagicMock()
    svc._db.fetch_query.return_value = ([], [])
    svc._load_candidate_ratings = MagicMock(
        return_value=[
            {
                "id": 9,
                "ticker": "MSFT",
                "rating": "HOLD",
                "score": 0,
                "report_type": "core",
                "price_summary": {"live_price": 100.0},
                "created_at": rated,
                "report_live_price": None,
            }
        ]
    )
    svc._load_daily_closes = MagicMock(return_value=closes)

    out = svc.refresh()
    assert out["updated"] == 1
    assert mock_snaps.called
    params = svc._db.execute_query.call_args[0][1]
    assert abs(params[8] - 0.04) < 1e-9  # return_5d
    assert abs(params[11] - 0.19) < 1e-9  # return_20d
    assert params[13] is True  # direction_hit_5d
    assert params[14] is False  # direction_hit_20d
    assert params[15] == "complete"


def test_regrade_hold_direction_hits_is_idempotent():
    svc = OutcomeService()
    db = MagicMock()
    db.fetch_query.return_value = (
        [
            (1, 0.04, 0.19, None, None),
            (2, 0.10, -0.15, None, None),
            (3, None, 0.01, None, True),
        ],
        [],
    )
    svc._db = db
    svc.refresh_calibration_snapshots = MagicMock(return_value=4)

    out = svc.regrade_hold_direction_hits()
    assert out == {"hold_rows": 3, "updated": 2, "snapshots": 4}
    pending = db.execute_many.call_args[0][1]
    by_id = {row[2]: (row[0], row[1]) for row in pending}
    assert by_id[1] == (True, False)
    assert by_id[2] == (False, False)
    assert 3 not in by_id

    db.fetch_query.return_value = (
        [
            (1, 0.04, 0.19, True, False),
            (2, 0.10, -0.15, False, False),
            (3, None, 0.01, None, True),
        ],
        [],
    )
    db.execute_many.reset_mock()
    again = svc.regrade_hold_direction_hits()
    assert again["updated"] == 0
    db.execute_many.assert_not_called()


def test_refresh_holds_only_skips_the_price_walk():
    svc = OutcomeService()
    svc._load_candidate_ratings = MagicMock(side_effect=AssertionError("price walk"))
    svc.regrade_hold_direction_hits = MagicMock(
        return_value={"hold_rows": 4, "updated": 4, "snapshots": 2}
    )
    out = svc.refresh(holds_only=True)
    assert out["holds_only"] is True
    assert out["updated"] == 4
    assert out["snapshots"] == 2
    assert out["candidates"] == 4
    svc._load_candidate_ratings.assert_not_called()


def test_calibration_snapshot_counts_scored_holds():
    svc = OutcomeService()
    db = MagicMock()
    db.fetch_query.return_value = (
        [
            ("HOLD", 0, "core", 0.02, 0.20, True, False, "complete"),
            ("BUY", 50, "core", 0.01, 0.03, True, True, "complete"),
            ("HOLD", 4, "core", None, 0.01, None, None, "partial"),
        ],
        [],
    )
    svc._db = db
    count = svc.refresh_calibration_snapshots(as_of=date(2026, 11, 16))
    inserts = [
        call.args[1]
        for call in db.execute_query.call_args_list
        if "INSERT INTO analysis_calibration_snapshots" in call.args[0]
    ]
    by_key = {(row[1], row[2]): row for row in inserts}
    hold_5d = by_key[("5d", "rating=HOLD")]
    hold_20d = by_key[("20d", "rating=HOLD")]
    # 5d HOLD has one scored hit. The partial row has no 5d return, so it is absent.
    assert hold_5d[3] == 1  # n
    assert hold_5d[4] == 1.0  # hit_rate
    # 20d: one miss with a return, one unscored (null hit) with a return.
    # n includes the return; hit_rate uses only scored rows.
    assert hold_20d[3] == 2
    assert hold_20d[4] == 0.0
    assert count == len(inserts)
