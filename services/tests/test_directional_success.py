"""Directional-success card: weekly core hit rate and latest ready week."""
from datetime import datetime, timezone

from services.directional_success import build_directional_success, hkt_week_start


def _row(
    *,
    rating_id: int,
    ticker: str,
    rated_at: datetime,
    rating: str,
    score: int,
    report_type: str = "core",
    return_5d: float | None = 0.01,
    return_20d: float | None = 0.02,
    direction_hit_5d: bool | None = True,
    direction_hit_20d: bool | None = True,
    status: str | None = "complete",
) -> dict:
    return {
        "rating_id": rating_id,
        "ticker": ticker,
        "rated_at": rated_at,
        "rating": rating,
        "score": score,
        "report_type": report_type,
        "return_5d": return_5d,
        "return_20d": return_20d,
        "direction_hit_5d": direction_hit_5d,
        "direction_hit_20d": direction_hit_20d,
        "status": status,
    }


# Monday 2026-11-02 19:00 HKT == 11:00 UTC (weekly job).
WEEK_A = datetime(2026, 11, 2, 11, 0, tzinfo=timezone.utc)
# Later core the same HKT week (Friday 2026-11-06 02:00 HKT).
WEEK_A_LATER = datetime(2026, 11, 5, 18, 0, tzinfo=timezone.utc)
# Next Monday 2026-11-09 19:00 HKT.
WEEK_B = datetime(2026, 11, 9, 11, 0, tzinfo=timezone.utc)


def test_hkt_week_starts_monday():
    # Sunday 2026-11-08 23:59 HKT == 15:59 UTC still belongs to the week of Nov 2.
    sunday = datetime(2026, 11, 8, 15, 59, tzinfo=timezone.utc)
    # Monday 2026-11-09 00:00 HKT == 16:00 UTC Sunday opens the next week.
    monday = datetime(2026, 11, 8, 16, 0, tzinfo=timezone.utc)
    assert hkt_week_start(sunday).isoformat() == "2026-11-02"
    assert hkt_week_start(monday).isoformat() == "2026-11-09"
    assert hkt_week_start(WEEK_A).isoformat() == "2026-11-02"
    assert hkt_week_start(WEEK_A_LATER).isoformat() == "2026-11-02"


def test_one_core_row_per_ticker_per_hkt_week_keeps_earliest():
    """Weekly baseline is the first core write of the HKT week, not a later rerun."""
    card = build_directional_success(
        [
            _row(
                rating_id=1,
                ticker="aapl",
                rated_at=WEEK_A,
                rating="BUY",
                score=48,
                return_5d=0.03,
                direction_hit_5d=True,
            ),
            _row(
                rating_id=2,
                ticker="AAPL",
                rated_at=WEEK_A_LATER,
                rating="SELL",
                score=-40,
                return_5d=-0.05,
                direction_hit_5d=True,
            ),
            _row(
                rating_id=3,
                ticker="NVDA",
                rated_at=WEEK_A,
                rating="BUY",
                score=60,
                report_type="deep",
                return_5d=0.10,
                direction_hit_5d=True,
            ),
        ]
    )
    rows = card["week"]["rows"]
    assert card["week"]["status"] == "ready"
    assert card["week"]["week_start"] == "2026-11-02"
    assert [r["ticker"] for r in rows] == ["AAPL"]
    assert rows[0]["rating"] == "BUY"
    assert rows[0]["score"] == 48
    assert rows[0]["outcome"] == "hit"
    assert card["overall"]["5d"]["n"] == 1
    assert card["overall"]["5d"]["hits"] == 1
    assert card["overall"]["5d"]["hit_rate"] == 1.0


def test_hold_is_listed_and_excluded_from_denominator():
    card = build_directional_success(
        [
            _row(
                rating_id=1,
                ticker="AAPL",
                rated_at=WEEK_A,
                rating="BUY",
                score=40,
                return_5d=0.02,
                return_20d=-0.01,
                direction_hit_5d=True,
                direction_hit_20d=False,
            ),
            _row(
                rating_id=2,
                ticker="MSFT",
                rated_at=WEEK_A,
                rating="HOLD",
                score=0,
                return_5d=0.04,
                return_20d=0.05,
                direction_hit_5d=None,
                direction_hit_20d=None,
            ),
            _row(
                rating_id=3,
                ticker="IBM",
                rated_at=WEEK_A,
                rating="SELL",
                score=-45,
                return_5d=0.01,
                return_20d=-0.02,
                direction_hit_5d=False,
                direction_hit_20d=True,
            ),
        ]
    )
    outcomes = {r["ticker"]: r["outcome"] for r in card["week"]["rows"]}
    assert outcomes == {"AAPL": "hit", "IBM": "miss", "MSFT": "unscored"}
    assert card["overall"]["5d"] == {"hit_rate": 0.5, "hits": 1, "n": 2}
    assert card["overall"]["20d"] == {"hit_rate": 0.5, "hits": 1, "n": 2}


def test_pending_latest_week_falls_back_to_previous_complete_week():
    card = build_directional_success(
        [
            _row(
                rating_id=1,
                ticker="AAPL",
                rated_at=WEEK_A,
                rating="BUY",
                score=44,
                return_5d=0.02,
                direction_hit_5d=True,
            ),
            _row(
                rating_id=2,
                ticker="MSFT",
                rated_at=WEEK_B,
                rating="BUY",
                score=50,
                return_5d=None,
                return_20d=None,
                direction_hit_5d=None,
                direction_hit_20d=None,
                status="pending",
            ),
            _row(
                rating_id=3,
                ticker="NVDA",
                rated_at=WEEK_B,
                rating="SELL",
                score=-42,
                return_5d=None,
                return_20d=None,
                direction_hit_5d=None,
                direction_hit_20d=None,
                status=None,
            ),
        ]
    )
    assert card["week"]["status"] == "pending_fallback"
    assert card["week"]["week_start"] == "2026-11-02"
    assert card["week"]["week_end"] == "2026-11-08"
    assert card["week"]["pending_week_start"] == "2026-11-09"
    assert card["week"]["rows"][0]["ticker"] == "AAPL"
    assert "not" in card["week"]["message"].lower()
    assert "2026-11-09" in card["week"]["message"]
    assert "2026-11-02" in card["week"]["message"]
    # History still counts scored core rows. The open week has none yet.
    assert card["overall"]["5d"]["n"] == 1
    assert card["overall"]["5d"]["hit_rate"] == 1.0


def test_ready_latest_week_is_the_breakdown():
    card = build_directional_success(
        [
            _row(
                rating_id=1,
                ticker="AAPL",
                rated_at=WEEK_A,
                rating="BUY",
                score=40,
                direction_hit_5d=True,
            ),
            _row(
                rating_id=2,
                ticker="MSFT",
                rated_at=WEEK_B,
                rating="REDUCE",
                score=-20,
                return_5d=-0.03,
                direction_hit_5d=True,
            ),
        ]
    )
    assert card["week"]["status"] == "ready"
    assert card["week"]["week_start"] == "2026-11-09"
    assert card["week"]["pending_week_start"] is None
    assert card["week"]["message"] is None
    assert [r["ticker"] for r in card["week"]["rows"]] == ["MSFT"]
    assert card["overall"]["5d"]["n"] == 2


def test_skipped_row_does_not_block_a_ready_week():
    card = build_directional_success(
        [
            _row(
                rating_id=1,
                ticker="AAPL",
                rated_at=WEEK_B,
                rating="BUY",
                score=41,
                direction_hit_5d=True,
            ),
            _row(
                rating_id=2,
                ticker="IBM",
                rated_at=WEEK_B,
                rating="BUY",
                score=33,
                return_5d=None,
                return_20d=None,
                direction_hit_5d=None,
                direction_hit_20d=None,
                status="skipped",
            ),
        ]
    )
    assert card["week"]["status"] == "ready"
    assert card["week"]["week_start"] == "2026-11-09"
    outcomes = {r["ticker"]: r["outcome"] for r in card["week"]["rows"]}
    assert outcomes["IBM"] == "unscored"
    assert card["overall"]["5d"]["n"] == 1


def test_pending_week_with_no_earlier_complete_week():
    card = build_directional_success(
        [
            _row(
                rating_id=1,
                ticker="AAPL",
                rated_at=WEEK_B,
                rating="BUY",
                score=40,
                return_5d=None,
                direction_hit_5d=None,
                status="pending",
            )
        ]
    )
    assert card["week"]["status"] == "pending"
    assert card["week"]["week_start"] is None
    assert card["week"]["rows"] == []
    assert card["week"]["pending_week_start"] == "2026-11-09"
    assert card["overall"]["5d"]["n"] == 0
    assert card["overall"]["5d"]["hit_rate"] is None


def test_empty_history():
    card = build_directional_success([])
    assert card["scope"] == "core"
    assert "experiment" in card["disclaimer"].lower()
    assert "promise" in card["disclaimer"].lower()
    assert card["week"]["status"] == "empty"
    assert card["week"]["rows"] == []
    assert card["overall"]["5d"]["n"] == 0
    assert card["overall"]["20d"]["n"] == 0


def test_directional_success_query_is_core_only_and_joins_outcomes():
    from unittest.mock import MagicMock

    from services.outcome_service import OutcomeService

    svc = OutcomeService()
    db = MagicMock()
    db.fetch_query.return_value = (
        [],
        [
            "rating_id",
            "ticker",
            "rated_at",
            "rating",
            "score",
            "report_type",
            "return_5d",
            "return_20d",
            "direction_hit_5d",
            "direction_hit_20d",
            "status",
        ],
    )
    svc._db = db

    card = svc.directional_success()

    sql = db.fetch_query.call_args[0][0]
    assert "LEFT JOIN rating_outcomes" in sql
    assert "r.report_type = 'core'" in sql
    assert "r.decision_ok IS TRUE" in sql
    assert card["week"]["status"] == "empty"
    assert card["scope"] == "core"
