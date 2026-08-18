"""Unit tests for JobQueueService (mocked DB)."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from services.job_queue_service import (
    DEFAULT_CORE_DURATION_SECONDS,
    DEFAULT_DEEP_DURATION_SECONDS,
    JOB_CORE,
    JOB_DEEP,
    JobQueueService,
    OwnershipLostError,
    resolve_duration_estimates,
    _row_to_job,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    JobQueueService._instance = None
    yield
    JobQueueService._instance = None


def _job_cols() -> list[str]:
    return [
        "id",
        "job_type",
        "ticker",
        "status",
        "cancel_requested",
        "progress",
        "result",
        "error",
        "worker_id",
        "lease_until",
        "created_at",
        "started_at",
        "finished_at",
        "updated_at",
    ]


def _job_row(
    job_id: str,
    *,
    job_type: str = JOB_CORE,
    ticker: str = "AAPL",
    status: str = "queued",
    cancel_requested: bool = False,
    worker_id: str | None = None,
    lease_until=None,
):
    return (
        job_id,
        job_type,
        ticker,
        status,
        cancel_requested,
        {},
        {},
        None,
        worker_id,
        lease_until,
        None,
        None,
        None,
        None,
    )


def test_enqueue_dedupes_active_job():
    db = MagicMock()
    existing_id = str(uuid4())
    cols = _job_cols()
    row = _job_row(existing_id, job_type=JOB_DEEP, ticker="AAPL", status="queued")
    # find_active then limits()
    db.fetch_query.side_effect = [
        ([row], cols),
        ([(1, 0)], ["running", "queued"]),
    ]

    with patch("services.job_queue_service.get_db_client", return_value=db):
        with patch("services.job_queue_service.UniverseService"):
            svc = JobQueueService()
            svc._started = True
            out = svc.enqueue(JOB_DEEP, ["AAPL"])

    assert out["started"] is True
    assert len(out["reused"]) == 1
    assert out["reused"][0]["id"] == existing_id
    assert out["enqueued"] == []
    db.execute_query.assert_not_called()


def test_cancel_queued_marks_cancelled():
    db = MagicMock()
    job_id = str(uuid4())
    cols = _job_cols()
    queued = _job_row(job_id, status="queued", ticker="MSFT")
    cancelled = _job_row(job_id, status="cancelled", ticker="MSFT")
    db.fetch_query.side_effect = [
        ([queued], cols),
        ([cancelled], cols),
    ]

    with patch("services.job_queue_service.get_db_client", return_value=db):
        with patch("services.job_queue_service.UniverseService"):
            svc = JobQueueService()
            svc._started = True
            out = svc.cancel(job_id)

    assert out["ok"] is True
    assert out["job"]["status"] == "cancelled"
    assert db.execute_query.called


def test_cancel_running_sets_flag():
    db = MagicMock()
    job_id = str(uuid4())
    cols = _job_cols()
    running = _job_row(job_id, status="running", ticker="GOOGL")
    flagged = _job_row(
        job_id, status="running", ticker="GOOGL", cancel_requested=True
    )
    db.fetch_query.side_effect = [
        ([running], cols),
        ([flagged], cols),
    ]

    with patch("services.job_queue_service.get_db_client", return_value=db):
        with patch("services.job_queue_service.UniverseService"):
            svc = JobQueueService()
            svc._started = True
            out = svc.cancel(job_id)

    assert out["ok"] is True
    assert out["job"]["cancel_requested"] is True
    sql = db.execute_query.call_args.args[0]
    assert "cancel_requested = TRUE" in sql


def test_reclaim_only_expired_leases():
    db = MagicMock()
    with patch("services.job_queue_service.get_db_client", return_value=db):
        with patch("services.job_queue_service.UniverseService"):
            svc = JobQueueService()
            svc._reclaim_expired_jobs()

    assert db.execute_query.call_count >= 2
    sqls = " ".join(c.args[0] for c in db.execute_query.call_args_list)
    assert "lease_until IS NULL OR lease_until < NOW()" in sqls
    assert "status = 'queued'" in sqls
    assert "cancel_requested = TRUE" in sqls or "cancelled" in sqls
    # Must not blindly requeue all running jobs
    assert "WHERE status = 'running' AND cancel_requested = FALSE\n" not in sqls or (
        "lease_until" in sqls
    )


def test_maybe_reclaim_respects_interval():
    db = MagicMock()
    with patch("services.job_queue_service.get_db_client", return_value=db):
        with patch("services.job_queue_service.UniverseService"):
            with patch(
                "services.job_queue_service._reclaim_interval_seconds",
                return_value=20,
            ):
                svc = JobQueueService()
                svc._last_reclaim_at = time.monotonic()
                with patch.object(svc, "_reclaim_expired_jobs") as reclaim:
                    svc._maybe_reclaim()
                    reclaim.assert_not_called()
                    svc._last_reclaim_at = time.monotonic() - 21
                    svc._maybe_reclaim()
                    reclaim.assert_called_once()


def test_heal_alias_calls_reclaim():
    db = MagicMock()
    with patch("services.job_queue_service.get_db_client", return_value=db):
        with patch("services.job_queue_service.UniverseService"):
            svc = JobQueueService()
            svc._heal_running_jobs()

    sqls = " ".join(c.args[0] for c in db.execute_query.call_args_list)
    assert "lease_until" in sqls


def test_claim_returns_none_when_at_max_concurrent():
    db = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = (1,)  # running count == max
    conn = MagicMock()
    conn.cursor.return_value = cur
    db.checkout.return_value.__enter__.return_value = conn
    db.checkout.return_value.__exit__.return_value = None

    with patch("services.job_queue_service.get_db_client", return_value=db):
        with patch("services.job_queue_service.UniverseService"):
            with patch("services.job_queue_service._max_concurrent", return_value=1):
                svc = JobQueueService()
                svc._started = True
                claimed = svc._claim_next()

    assert claimed is None
    select_sqls = [c.args[0] for c in cur.execute.call_args_list if c.args]
    assert any("COUNT(*)" in s for s in select_sqls)
    assert not any("FOR UPDATE SKIP LOCKED" in s for s in select_sqls)


def test_claim_sets_worker_id_and_lease():
    db = MagicMock()
    job_id = str(uuid4())
    cur = MagicMock()
    # COUNT running -> 0; SELECT id; RETURNING id
    cur.fetchone.side_effect = [(0,), (job_id,), (job_id,)]
    conn = MagicMock()
    conn.cursor.return_value = cur
    db.checkout.return_value.__enter__.return_value = conn
    db.checkout.return_value.__exit__.return_value = None

    job_row = {
        "id": job_id,
        "job_type": JOB_DEEP,
        "ticker": "NVDA",
        "status": "running",
        "cancel_requested": False,
        "progress": {},
        "result": {},
        "error": None,
        "worker_id": "test-worker",
        "lease_until": "2026-08-06T00:00:00+00:00",
        "created_at": None,
        "started_at": None,
        "finished_at": None,
        "updated_at": None,
    }

    with patch("services.job_queue_service.get_db_client", return_value=db):
        with patch("services.job_queue_service.UniverseService"):
            with patch("services.job_queue_service._max_concurrent", return_value=1):
                with patch(
                    "services.job_queue_service._worker_id",
                    return_value="test-worker",
                ):
                    with patch(
                        "services.job_queue_service._lease_seconds",
                        return_value=60,
                    ):
                        with patch(
                            "services.job_queue_service._claim_delay_seconds",
                            return_value=0,
                        ):
                            svc = JobQueueService()
                            svc._started = True
                            with patch.object(svc, "get_job", return_value=job_row):
                                claimed = svc._claim_next()

    assert claimed is not None
    assert claimed["id"] == job_id
    sqls = " ".join(c.args[0] for c in cur.execute.call_args_list)
    assert "FOR UPDATE SKIP LOCKED" in sqls
    assert "worker_id = %s" in sqls
    assert "lease_until = NOW()" in sqls
    # claim delay param passed as 0
    claim_select = [
        c for c in cur.execute.call_args_list if "FOR UPDATE SKIP LOCKED" in c.args[0]
    ]
    assert claim_select
    assert claim_select[0].args[1] == (0,)


def test_claim_delay_filter_uses_env_seconds():
    db = MagicMock()
    cur = MagicMock()
    cur.fetchone.side_effect = [(0,), None]  # under capacity, no eligible job
    conn = MagicMock()
    conn.cursor.return_value = cur
    db.checkout.return_value.__enter__.return_value = conn
    db.checkout.return_value.__exit__.return_value = None

    with patch("services.job_queue_service.get_db_client", return_value=db):
        with patch("services.job_queue_service.UniverseService"):
            with patch("services.job_queue_service._max_concurrent", return_value=1):
                with patch(
                    "services.job_queue_service._claim_delay_seconds",
                    return_value=45,
                ):
                    svc = JobQueueService()
                    svc._started = True
                    claimed = svc._claim_next()

    assert claimed is None
    claim_select = [
        c for c in cur.execute.call_args_list if "FOR UPDATE SKIP LOCKED" in c.args[0]
    ]
    assert claim_select
    assert "created_at <= NOW()" in claim_select[0].args[0]
    assert claim_select[0].args[1] == (45,)


def test_row_to_job_includes_lease_fields():
    cols = _job_cols()
    row = _job_row(
        str(uuid4()),
        status="running",
        worker_id="local-1",
        lease_until="2026-08-06T12:00:00+00:00",
    )
    job = _row_to_job(row, cols)
    assert job["worker_id"] == "local-1"
    assert job["lease_until"] == "2026-08-06T12:00:00+00:00"


def test_set_progress_raises_when_ownership_lost():
    db = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = None  # no RETURNING row
    conn = MagicMock()
    conn.cursor.return_value = cur
    db.checkout.return_value.__enter__.return_value = conn
    db.checkout.return_value.__exit__.return_value = None

    with patch("services.job_queue_service.get_db_client", return_value=db):
        with patch("services.job_queue_service.UniverseService"):
            with patch(
                "services.job_queue_service._worker_id", return_value="me"
            ):
                svc = JobQueueService()
                svc._started = True
                with pytest.raises(OwnershipLostError):
                    svc._set_progress(str(uuid4()), message="x")


def test_renew_lease_returns_false_when_lost():
    db = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = None
    conn = MagicMock()
    conn.cursor.return_value = cur
    db.checkout.return_value.__enter__.return_value = conn
    db.checkout.return_value.__exit__.return_value = None

    with patch("services.job_queue_service.get_db_client", return_value=db):
        with patch("services.job_queue_service.UniverseService"):
            with patch(
                "services.job_queue_service._worker_id", return_value="me"
            ):
                svc = JobQueueService()
                svc._started = True
                ok = svc._renew_lease(str(uuid4()))

    assert ok is False
    sql = cur.execute.call_args.args[0]
    assert "lease_until = NOW()" in sql
    assert "worker_id = %s" in sql


def test_should_stop_when_worker_mismatch():
    db = MagicMock()
    job_id = str(uuid4())
    db.fetch_query.return_value = (
        [(False, "other-worker", "running")],
        ["cancel_requested", "worker_id", "status"],
    )

    with patch("services.job_queue_service.get_db_client", return_value=db):
        with patch("services.job_queue_service.UniverseService"):
            with patch(
                "services.job_queue_service._worker_id", return_value="me"
            ):
                svc = JobQueueService()
                svc._started = True
                assert svc._should_stop(job_id) is True


def test_should_stop_false_when_owned_and_running():
    db = MagicMock()
    job_id = str(uuid4())
    db.fetch_query.return_value = (
        [(False, "me", "running")],
        ["cancel_requested", "worker_id", "status"],
    )

    with patch("services.job_queue_service.get_db_client", return_value=db):
        with patch("services.job_queue_service.UniverseService"):
            with patch(
                "services.job_queue_service._worker_id", return_value="me"
            ):
                svc = JobQueueService()
                svc._started = True
                assert svc._should_stop(job_id) is False


def test_resolve_duration_estimates_fallback_with_zero_or_one_sample():
    assert resolve_duration_estimates([]) == {
        JOB_CORE: float(DEFAULT_CORE_DURATION_SECONDS),
        JOB_DEEP: float(DEFAULT_DEEP_DURATION_SECONDS),
    }
    one = resolve_duration_estimates([(JOB_CORE, 100.0, 1)])
    assert one[JOB_CORE] == float(DEFAULT_CORE_DURATION_SECONDS)
    assert one[JOB_DEEP] == float(DEFAULT_DEEP_DURATION_SECONDS)


def test_resolve_duration_estimates_uses_average_when_enough_samples():
    out = resolve_duration_estimates(
        [(JOB_CORE, 187.44, 8), (JOB_DEEP, 248.12, 5)]
    )
    assert out[JOB_CORE] == 187.4
    assert out[JOB_DEEP] == 248.1


def test_duration_estimates_query_filters_outliers_and_caches():
    db = MagicMock()
    db.fetch_query.return_value = (
        [(JOB_CORE, 180.0, 8), (JOB_DEEP, 250.0, 3)],
        ["job_type", "avg_seconds", "n"],
    )

    with patch("services.job_queue_service.get_db_client", return_value=db):
        with patch("services.job_queue_service.UniverseService"):
            svc = JobQueueService()
            first = svc.duration_estimates()
            second = svc.duration_estimates()

    assert first == {JOB_CORE: 180.0, JOB_DEEP: 250.0}
    assert second == first
    assert db.fetch_query.call_count == 1
    sql = db.fetch_query.call_args[0][0]
    params = db.fetch_query.call_args[0][1]
    assert "BETWEEN" in sql
    assert "ROW_NUMBER" in sql
    assert params[2] == 15
    assert params[3] == 1800
    assert params[4] == 8


def test_duration_estimates_cache_expires():
    db = MagicMock()
    db.fetch_query.side_effect = [
        ([(JOB_CORE, 180.0, 8)], ["job_type", "avg_seconds", "n"]),
        ([(JOB_CORE, 200.0, 8)], ["job_type", "avg_seconds", "n"]),
    ]

    with patch("services.job_queue_service.get_db_client", return_value=db):
        with patch("services.job_queue_service.UniverseService"):
            svc = JobQueueService()
            svc.duration_estimates()
            svc._duration_cache_at = 0.0
            out = svc.duration_estimates()

    assert out[JOB_CORE] == 200.0
    assert db.fetch_query.call_count == 2


def test_finish_strips_thinking_key():
    db = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = ("job-id",)
    conn = MagicMock()
    conn.cursor.return_value = cur
    db.checkout.return_value.__enter__.return_value = conn
    db.checkout.return_value.__exit__.return_value = None
    db.fetch_query.return_value = ([], [])

    with patch("services.job_queue_service.get_db_client", return_value=db):
        with patch("services.job_queue_service.UniverseService"):
            with patch(
                "services.job_queue_service._worker_id", return_value="me"
            ):
                svc = JobQueueService()
                svc._started = True
                svc._finish(str(uuid4()), "done", message="Done")

    sql = cur.execute.call_args[0][0]
    assert "- 'thinking'" in sql


def test_finish_skips_checkpoint_when_ownership_lost():
    db = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = None
    conn = MagicMock()
    conn.cursor.return_value = cur
    db.checkout.return_value.__enter__.return_value = conn
    db.checkout.return_value.__exit__.return_value = None

    with patch("services.job_queue_service.get_db_client", return_value=db):
        with patch("services.job_queue_service.UniverseService"):
            with patch(
                "services.job_queue_service._worker_id", return_value="me"
            ):
                svc = JobQueueService()
                svc._started = True
                with patch.object(svc, "_append_analysis_checkpoint") as append:
                    svc._finish(
                        str(uuid4()),
                        "done",
                        result={"ticker": "AAPL", "rating": "HOLD"},
                        message="Done",
                    )
                append.assert_not_called()
