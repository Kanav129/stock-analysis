"""Smoke tests for /jobs enqueue → list → cancel (router-only, no full app)."""
from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rest_api.routes.jobs_routes import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


def test_enqueue_list_cancel_flow():
    job_id = str(uuid4())
    job = {
        "id": job_id,
        "job_type": "deep_dive",
        "ticker": "AAPL",
        "status": "queued",
        "cancel_requested": False,
        "progress": {},
        "result": {},
        "error": None,
        "created_at": None,
        "started_at": None,
        "finished_at": None,
        "updated_at": None,
    }
    limits = {"max_concurrent": 1, "running": 0, "queued": 1}

    with (
        patch("rest_api.routes.jobs_routes.job_queue_service.ensure_started"),
        patch(
            "rest_api.routes.jobs_routes.job_queue_service.enqueue",
            return_value={
                "started": True,
                "enqueued": [job],
                "reused": [],
                "jobs": [job],
                "message": "Queued 1",
                "limits": limits,
            },
        ) as enq,
        patch(
            "rest_api.routes.jobs_routes.job_queue_service.list_jobs",
            return_value=[job],
        ),
        patch(
            "rest_api.routes.jobs_routes.job_queue_service.limits",
            return_value=limits,
        ),
        patch(
            "rest_api.routes.jobs_routes.sync_service.get_status",
            return_value={"running": False, "status": "idle"},
        ),
        patch(
            "rest_api.routes.jobs_routes.analysis_service.get_status",
            return_value={
                "running": False,
                "status": "idle",
                "tickers": [],
                "total": 0,
                "current_index": 0,
                "current_ticker": None,
                "stage": None,
                "stage_label": None,
                "completed": [],
                "errors": [],
                "percent": 0,
                "message": "",
                "started_at": None,
                "finished_at": None,
                "last_run": None,
            },
        ),
        patch(
            "rest_api.routes.jobs_routes.job_queue_service.cancel",
            return_value={"ok": True, "job": {**job, "status": "cancelled"}},
        ) as cancel,
    ):
        enq_resp = client.post(
            "/jobs",
            json={"job_type": "deep_dive", "tickers": ["AAPL"]},
        )
        assert enq_resp.status_code == 200
        assert enq_resp.json()["enqueued"][0]["id"] == job_id
        enq.assert_called_once()

        list_resp = client.get("/jobs")
        assert list_resp.status_code == 200
        body = list_resp.json()
        assert body["jobs"][0]["ticker"] == "AAPL"
        assert body["limits"]["max_concurrent"] == 1
        assert body["analysis"]["status"] == "idle"

        cancel_resp = client.post(f"/jobs/{job_id}/cancel")
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["ok"] is True
        cancel.assert_called_once_with(job_id)


def test_list_jobs_lite_skips_analysis_when_idle():
    limits = {"max_concurrent": 1, "running": 0, "queued": 0}
    with (
        patch("rest_api.routes.jobs_routes.job_queue_service.ensure_started"),
        patch(
            "rest_api.routes.jobs_routes.job_queue_service.list_jobs",
            return_value=[],
        ),
        patch(
            "rest_api.routes.jobs_routes.job_queue_service.limits",
            return_value=limits,
        ),
        patch(
            "rest_api.routes.jobs_routes.sync_service.get_status",
            return_value={"running": False, "status": "idle"},
        ),
        patch(
            "rest_api.routes.jobs_routes.analysis_service.get_status",
        ) as analysis,
    ):
        lite_resp = client.get("/jobs?lite=1")
    assert lite_resp.status_code == 200
    body = lite_resp.json()
    assert body["jobs"] == []
    assert "analysis" not in body
    analysis.assert_not_called()


def test_enqueue_rejects_bad_job_type():
    resp = client.post("/jobs", json={"job_type": "sync", "tickers": ["AAPL"]})
    assert resp.status_code == 400


def test_cancel_all():
    with patch(
        "rest_api.routes.jobs_routes.job_queue_service.cancel_all",
        return_value={"ok": True, "jobs": [], "limits": {"max_concurrent": 1, "running": 0, "queued": 0}},
    ) as cancel_all:
        resp = client.post("/jobs/cancel-all")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    cancel_all.assert_called_once()
