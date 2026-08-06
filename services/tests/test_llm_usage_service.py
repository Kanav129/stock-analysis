"""Tests for LLM usage extraction and aggregation."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.llm_usage_service import (
    LlmUsageService,
    _empty_bucket,
    extract_token_usage,
)


def test_extract_from_usage_metadata():
    msg = SimpleNamespace(
        usage_metadata={"input_tokens": 100, "output_tokens": 40},
        response_metadata={},
    )
    assert extract_token_usage(msg) == (100, 40)


def test_extract_from_response_metadata_token_usage():
    msg = SimpleNamespace(
        usage_metadata=None,
        response_metadata={"token_usage": {"prompt_tokens": 12, "completion_tokens": 8}},
    )
    assert extract_token_usage(msg) == (12, 8)


def test_extract_from_include_raw_dict():
    raw = SimpleNamespace(
        usage_metadata={"input_tokens": 50, "output_tokens": 25},
        response_metadata={},
    )
    payload = {"raw": raw, "parsed": SimpleNamespace(rating="BUY")}
    assert extract_token_usage(payload) == (50, 25)


def test_extract_empty():
    assert extract_token_usage(None) == (0, 0)
    assert extract_token_usage(SimpleNamespace()) == (0, 0)


@patch("services.llm_usage_service.get_db_client")
def test_record_best_effort_insert(mock_db):
    db = MagicMock()
    mock_db.return_value = db
    msg = SimpleNamespace(
        usage_metadata={"input_tokens": 1000, "output_tokens": 500},
        response_metadata={},
    )
    LlmUsageService().record_from_result(role="research", model="qwen3.7-flash", result=msg)
    assert db.execute_query.called
    args = db.execute_query.call_args[0]
    assert "INSERT INTO llm_usage" in args[0]
    assert args[1][0] == "research"
    assert args[1][1] == "qwen3.7-flash"
    assert args[1][2] == 1000
    assert args[1][3] == 500


@patch("services.llm_usage_service.get_db_client")
def test_record_swallows_db_errors(mock_db):
    mock_db.side_effect = RuntimeError("db down")
    LlmUsageService().record(role="analysis", model="qwen3.7-max", input_tokens=10, output_tokens=5)


@patch("services.llm_usage_service.today_key", return_value="2026-08-06")
@patch("services.llm_usage_service.day_bounds_utc")
@patch.object(LlmUsageService, "_fetch_rows")
def test_get_usage_summary_zero_fills_and_splits(mock_fetch, mock_bounds, mock_today):
    # Map day_bounds_utc to fixed UTC windows for predictable aggregation
    def bounds(day: str | None = None):
        day = day or "2026-08-06"
        y, m, d = (int(x) for x in day.split("-"))
        start = datetime(y, m, d, 0, 0, tzinfo=timezone.utc) - timedelta(hours=8)
        end = start + timedelta(days=1)
        return start, end

    mock_bounds.side_effect = bounds

    today_start, _ = bounds("2026-08-06")
    rows = [
        (today_start + timedelta(hours=1), "analysis", 1000, 200, 0.01),
        (today_start + timedelta(hours=2), "research", 5000, 1000, 0.002),
        (today_start - timedelta(days=3), "research", 2000, 400, 0.001),
    ]
    mock_fetch.return_value = rows

    summary = LlmUsageService().get_usage_summary("week")
    assert summary["range"] == "week"
    assert len(summary["daily"]) == 7
    assert summary["periods"]["today"]["analysis"]["input_tokens"] == 1000
    assert summary["periods"]["today"]["research"]["input_tokens"] == 5000
    assert summary["periods"]["today"]["total"]["input_tokens"] == 6000
    assert summary["periods"]["week"]["research"]["input_tokens"] == 7000

    today_row = next(d for d in summary["daily"] if d["date"] == "2026-08-06")
    assert today_row["analysis_tokens"] == 1200
    assert today_row["research_tokens"] == 6000
    # Zero-filled earlier day
    empty = next(d for d in summary["daily"] if d["date"] == "2026-07-31")
    assert empty["total_cost"] == 0
    assert empty["total_tokens"] == 0


def test_empty_bucket_shape():
    b = _empty_bucket()
    assert b == {"cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
