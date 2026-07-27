"""Unit tests for JobQueueService (mocked DB)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from services.job_queue_service import (
    JOB_CORE,
    JOB_DEEP,
    JobQueueService,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    JobQueueService._instance = None
    yield
    JobQueueService._instance = None


def _svc_with_db(db: MagicMock) -> JobQueueService:
    with patch("services.job_queue_service.get_db_client", return_value=db):
        with patch("services.job_queue_service.UniverseService") as uni:
            uni.return_value.get_tickers.return_value = ["AAPL", "MSFT"]
            svc = JobQueueService()
            svc._started = True  # skip worker start
            return svc


def test_enqueue_dedupes_active_job():
    db = MagicMock()
    existing_id = str(uuid4())
    cols = [
        "id",
        "job_type",
        "ticker",
        "status",
        "cancel_requested",
        "progress",
        "result",
        "error",
        "created_at",
        "started_at",
        "finished_at",
        "updated_at",
    ]
    row = (
        existing_id,
        JOB_DEEP,
        "AAPL",
        "queued",
        False,
        {},
        {},
        None,
        None,
        None,
        None,
        None,
    )
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
    cols = [
        "id",
        "job_type",
        "ticker",
        "status",
        "cancel_requested",
        "progress",
        "result",
        "error",
        "created_at",
        "started_at",
        "finished_at",
        "updated_at",
    ]
    queued = (
        job_id,
        JOB_CORE,
        "MSFT",
        "queued",
        False,
        {},
        {},
        None,
        None,
        None,
        None,
        None,
    )
    cancelled = (
        job_id,
        JOB_CORE,
        "MSFT",
        "cancelled",
        False,
        {},
        {},
        None,
        None,
        None,
        None,
        None,
    )
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
    cols = [
        "id",
        "job_type",
        "ticker",
        "status",
        "cancel_requested",
        "progress",
        "result",
        "error",
        "created_at",
        "started_at",
        "finished_at",
        "updated_at",
    ]
    running = (
        job_id,
        JOB_CORE,
        "GOOGL",
        "running",
        False,
        {},
        {},
        None,
        None,
        None,
        None,
        None,
    )
    flagged = (
        job_id,
        JOB_CORE,
        "GOOGL",
        "running",
        True,
        {},
        {},
        None,
        None,
        None,
        None,
        None,
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


def test_heal_requeues_running_without_cancel():
    db = MagicMock()
    with patch("services.job_queue_service.get_db_client", return_value=db):
        with patch("services.job_queue_service.UniverseService"):
            svc = JobQueueService()
            svc._heal_running_jobs()

    assert db.execute_query.call_count >= 2
    sqls = " ".join(c.args[0] for c in db.execute_query.call_args_list)
    assert "cancel_requested = TRUE" in sqls or "cancelled" in sqls
    assert "status = 'queued'" in sqls


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
    # Should not try to select queued jobs when at capacity
    select_sqls = [c.args[0] for c in cur.execute.call_args_list if c.args]
    assert any("COUNT(*)" in s for s in select_sqls)
    assert not any("FOR UPDATE SKIP LOCKED" in s for s in select_sqls)


def test_claim_promotes_queued_when_under_capacity():
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
        "created_at": None,
        "started_at": None,
        "finished_at": None,
        "updated_at": None,
    }

    with patch("services.job_queue_service.get_db_client", return_value=db):
        with patch("services.job_queue_service.UniverseService"):
            with patch("services.job_queue_service._max_concurrent", return_value=1):
                svc = JobQueueService()
                svc._started = True
                with patch.object(svc, "get_job", return_value=job_row):
                    claimed = svc._claim_next()

    assert claimed is not None
    assert claimed["id"] == job_id
    sqls = " ".join(c.args[0] for c in cur.execute.call_args_list)
    assert "FOR UPDATE SKIP LOCKED" in sqls
    assert "status = 'running'" in sqls
