"""The daily-sync wait loop must resume a zombie worker instead of polling forever."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "daily-sync.yml"


def _poll_script() -> str:
    text = WORKFLOW.read_text()
    start = text.index("def poll_action(")
    end = text.index('\n          sh("action"', start)
    block = text[start:end]
    lines = block.splitlines()
    indent = min(len(line) - len(line.lstrip(" ")) for line in lines if line.strip())
    return "\n".join(line[indent:] if line.strip() else "" for line in lines)


def _action(payload: dict) -> str:
    script = _poll_script() + "\nimport json, os\nprint(poll_action(json.loads(os.environ['SYNC_BODY'])))\n"
    result = subprocess.run(
        [sys.executable, "-c", script],
        input="",
        text=True,
        capture_output=True,
        env={"SYNC_BODY": json.dumps(payload)},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_workflow_does_not_treat_status_running_as_liveness():
    text = WORKFLOW.read_text()
    assert '[ "$running" = "True" ] || [ "$status" = "running" ]' not in text
    assert '[ "$action" = "wait" ]' in text
    assert '[ "$action" = "resume" ]' in text
    assert '[ "$action" = "success" ]' in text


def test_live_worker_keeps_waiting():
    assert _action({
        "running": True,
        "status": "running",
        "message": "Fetching news · VRTX (33/33)",
        "daily": {"status": "running", "can_resume": True, "already_completed_today": False},
    }) == "wait"


def test_zombie_running_flag_false_resumes_partial_checkpoint():
    """Observed 2026-11-05: status=running, running=false, prices done, news stuck."""
    assert _action({
        "running": False,
        "status": "running",
        "message": "Fetching news · VRTX (33/33)",
        "daily": {
            "status": "partial",
            "can_resume": True,
            "already_completed_today": False,
        },
    }) == "resume"


def test_missing_running_flag_with_unfinished_daily_checkpoint_resumes():
    assert _action({
        "status": "running",
        "daily": {"status": "running", "can_resume": False, "already_completed_today": False},
    }) == "resume"


def test_completed_sync_succeeds_even_if_post_stage_still_flagged_running():
    assert _action({
        "running": True,
        "status": "completed",
        "daily": {"status": "completed", "can_resume": False, "already_completed_today": True},
    }) == "success"


def test_idle_without_resumable_checkpoint_fails_the_wait():
    assert _action({
        "running": False,
        "status": "idle",
        "daily": {"status": "idle", "can_resume": False, "already_completed_today": False},
    }) == "fail"


def test_partial_checkpoint_resumes_when_worker_is_stopped():
    assert _action({
        "running": False,
        "status": "partial",
        "daily": {"status": "partial", "can_resume": True, "already_completed_today": False},
    }) == "resume"
