"""Model-requested deep dives sit on top of the |score| >= 30 auto-deep rule."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


def _result(
    *,
    score,
    recommended=False,
    reason="",
    decision_ok=True,
    report_id=11,
    error=None,
):
    payload = {
        "score": score,
        "decision_ok": decision_ok,
        "report_id": report_id,
        "deep_request": {"recommended": recommended, "reason": reason},
    }
    if error:
        payload["error_message"] = error
    return payload


def _run(result, *, same_day=None, active=None, used=0, cap=8):
    from services.job_queue_service import JobQueueService

    svc = JobQueueService()
    with (
        patch.object(svc, "find_active", return_value=active),
        patch(
            "services.report_service.ReportService.get_same_day_deep_report",
            return_value=same_day,
        ),
        patch(
            "services.report_service.ReportService.count_model_enqueued_deeps",
            return_value=used,
            create=True,
        ) as count,
        patch(
            "services.report_service.ReportService.record_core_deep_request",
            create=True,
        ) as record,
        patch.object(svc, "enqueue", return_value={"started": True}) as enq,
        patch(
            "config.rating_config.model_deep_weekly_cap",
            return_value=cap,
            create=True,
        ),
    ):
        svc._maybe_auto_enqueue_deep("aapl", result)
    return enq, record, count


def _recorded(record):
    assert record.called
    payload = record.call_args.args[1]
    return payload


def test_score_threshold_enqueues_when_model_says_no():
    enq, record, count = _run(
        _result(score=30, recommended=False, reason="Core already settles the week."),
    )

    enq.assert_called_once_with("deep_dive", ["AAPL"])
    saved = _recorded(record)
    assert saved["recommended"] is False
    assert saved["enqueued_by"] == "score"
    count.assert_not_called()


def test_model_yes_below_threshold_enqueues_when_skips_are_clear():
    enq, record, _count = _run(
        _result(
            score=12,
            recommended=True,
            reason="Lockup overhang is material and still unanswered.",
        ),
        same_day=None,
        active=None,
        used=0,
        cap=8,
    )

    enq.assert_called_once_with("deep_dive", ["AAPL"])
    saved = _recorded(record)
    assert saved["recommended"] is True
    assert saved["reason"] == "Lockup overhang is material and still unanswered."
    assert saved["enqueued_by"] == "model"
    assert record.call_args.args[0] == 11


def test_model_yes_with_empty_reason_does_not_enqueue():
    enq, record, count = _run(
        _result(score=18, recommended=True, reason="   "),
    )

    enq.assert_not_called()
    count.assert_not_called()
    saved = _recorded(record)
    assert saved["recommended"] is True
    assert saved["reason"] == ""
    assert saved["enqueued_by"] is None


def test_decision_ok_false_does_not_enqueue_model_or_score():
    enq, record, _count = _run(
        _result(
            score=44,
            recommended=True,
            reason="Flows could flip the call.",
            decision_ok=False,
        ),
    )

    enq.assert_not_called()
    record.assert_not_called()


def test_quota_failure_does_not_enqueue_model_or_score():
    enq, record, _count = _run(
        _result(
            score=12,
            recommended=True,
            reason="Policy question is still open.",
            error="403 quota exhausted",
        ),
    )

    enq.assert_not_called()
    record.assert_not_called()


def test_weekly_cap_blocks_model_request_but_not_score_threshold(caplog):
    from services.job_queue_service import JobQueueService

    svc = JobQueueService()
    with (
        patch.object(svc, "find_active", return_value=None),
        patch(
            "services.report_service.ReportService.get_same_day_deep_report",
            return_value=None,
        ),
        patch(
            "services.report_service.ReportService.count_model_enqueued_deeps",
            return_value=8,
            create=True,
        ) as count,
        patch(
            "services.report_service.ReportService.record_core_deep_request",
            create=True,
        ) as record,
        patch.object(svc, "enqueue", return_value={"started": True}) as enq,
        patch(
            "config.rating_config.model_deep_weekly_cap",
            return_value=8,
            create=True,
        ),
        caplog.at_level("INFO"),
    ):
        svc._maybe_auto_enqueue_deep(
            "AAPL",
            _result(
                score=12,
                recommended=True,
                reason="Flows could change this week's call.",
                report_id=4,
            ),
        )
        svc._maybe_auto_enqueue_deep(
            "MSFT",
            _result(
                score=33,
                recommended=False,
                reason="",
                report_id=5,
            ),
        )
        svc._maybe_auto_enqueue_deep(
            "NVDA",
            _result(
                score=41,
                recommended=True,
                reason="Flows could still matter, but the score rule fires first.",
                report_id=6,
            ),
        )

    assert [call.args for call in enq.call_args_list] == [
        ("deep_dive", ["MSFT"]),
        ("deep_dive", ["NVDA"]),
    ]
    count.assert_called_once()
    blocked = record.call_args_list[0].args[1]
    scored = record.call_args_list[1].args[1]
    scored_and_model = record.call_args_list[2].args[1]
    assert blocked["recommended"] is True
    assert blocked["enqueued_by"] == "cap_blocked"
    assert scored["enqueued_by"] == "score"
    assert scored_and_model["recommended"] is True
    assert scored_and_model["enqueued_by"] == "score"
    assert "cap" in caplog.text.lower()
    assert "AAPL" in caplog.text


def test_model_yes_enqueues_when_under_weekly_cap():
    enq, record, count = _run(
        _result(score=-8, recommended=True, reason="Policy risk is unanswered."),
        used=7,
        cap=8,
    )

    enq.assert_called_once_with("deep_dive", ["AAPL"])
    assert _recorded(record)["enqueued_by"] == "model"
    count.assert_called_once()


def test_same_day_deep_skips_model_request():
    enq, record, _count = _run(
        _result(score=9, recommended=True, reason="Debate could settle a messy core."),
        same_day={"id": 1},
    )

    enq.assert_not_called()
    assert _recorded(record)["enqueued_by"] is None
    assert _recorded(record)["recommended"] is True


def test_active_deep_skips_model_request():
    enq, record, _count = _run(
        _result(score=9, recommended=True, reason="Flows are the open question."),
        active={"id": "job-1"},
    )

    enq.assert_not_called()
    assert _recorded(record)["recommended"] is True
    assert _recorded(record)["enqueued_by"] is None


def test_count_model_enqueued_deeps_ignores_score_rule_rows():
    from services.report_service import ReportService

    svc = ReportService.__new__(ReportService)
    db = MagicMock()
    db.fetch_query.return_value = ([(2,)], ["count"])
    svc._db = db
    start = datetime(2026, 11, 15, 16, 0, tzinfo=timezone.utc)
    end = datetime(2026, 11, 22, 16, 0, tzinfo=timezone.utc)

    assert svc.count_model_enqueued_deeps(start, end) == 2
    sql, params = db.fetch_query.call_args.args
    assert "report_type = 'core'" in sql or "report_type='core'" in sql
    assert "enqueued_by" in sql
    assert "model" in sql
    assert "cap_blocked" not in sql
    assert params == (start, end)


def test_record_core_deep_request_writes_rating_json():
    from services.report_service import ReportService

    svc = ReportService.__new__(ReportService)
    db = MagicMock()
    svc._db = db
    svc.record_core_deep_request(
        11,
        {
            "recommended": True,
            "reason": "Policy could change the call.",
            "enqueued_by": "cap_blocked",
        },
    )
    sql, params = db.execute_query.call_args.args
    assert "jsonb_set" in sql
    assert "deep_request" in sql
    body = json.loads(params[0])
    assert body["recommended"] is True
    assert body["reason"] == "Policy could change the call."
    assert body["enqueued_by"] == "cap_blocked"
    assert params[1] == 11


def test_model_deep_weekly_cap_default_and_override(monkeypatch):
    from config.rating_config import model_deep_weekly_cap

    monkeypatch.delenv("MODEL_DEEP_WEEKLY_CAP", raising=False)
    assert model_deep_weekly_cap() == 8
    monkeypatch.setenv("MODEL_DEEP_WEEKLY_CAP", "3")
    assert model_deep_weekly_cap() == 3
    monkeypatch.setenv("MODEL_DEEP_WEEKLY_CAP", "0")
    assert model_deep_weekly_cap() == 0
    monkeypatch.setenv("MODEL_DEEP_WEEKLY_CAP", "none")
    assert model_deep_weekly_cap() is None
    monkeypatch.setenv("MODEL_DEEP_WEEKLY_CAP", "unlimited")
    assert model_deep_weekly_cap() is None


def test_run_core_forwards_model_deep_request():
    from services.job_queue_service import JobQueueService

    svc = JobQueueService()
    graph = MagicMock()
    graph.stream.return_value = [
        {
            "synthesize_decision": {
                "rating": "HOLD",
                "score": 12,
                "decision_ok": True,
                "deep_request": {
                    "recommended": True,
                    "reason": "Policy is open.",
                },
            }
        },
        {"persist": {"report_id": 21}},
    ]
    with (
        patch("rag_graphs.research_graph.graph.app", graph),
        patch.object(svc, "_set_stage_progress"),
        patch.object(svc, "_should_stop", return_value=False),
    ):
        out = svc._run_core("job-1", "aapl")

    assert out["report_id"] == 21
    assert out["score"] == 12
    assert out["deep_request"] == {
        "recommended": True,
        "reason": "Policy is open.",
    }


def test_hong_kong_week_starts_monday():
    from services import run_checkpoint_service as rcs

    # Wednesday 2026-11-18 02:00 UTC == 10:00 HKT, still the week of Monday the 16th.
    moment = datetime(2026, 11, 18, 2, 0, tzinfo=timezone.utc)
    with patch.dict("os.environ", {"APP_TIMEZONE": "Asia/Hong_Kong"}, clear=False):
        start, end = rcs.week_bounds_utc(moment)
    assert start == datetime(2026, 11, 15, 16, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 11, 22, 16, 0, tzinfo=timezone.utc)

    # Sunday 2026-11-15 15:00 UTC == 23:00 HKT belongs to the previous week.
    sunday = datetime(2026, 11, 15, 15, 0, tzinfo=timezone.utc)
    with patch.dict("os.environ", {"APP_TIMEZONE": "Asia/Hong_Kong"}, clear=False):
        prev_start, prev_end = rcs.week_bounds_utc(sunday)
    assert prev_end == start
    assert prev_start == datetime(2026, 11, 8, 16, 0, tzinfo=timezone.utc)
