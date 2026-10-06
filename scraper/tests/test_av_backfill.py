"""Daily Alpha Vantage drip: skip ETFs, rotate missing/stale names, cap the batch."""
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scraper.av_backfill import (
    DEFAULT_DAILY_REQUESTS,
    DEFAULT_DAILY_TICKERS,
    BackfillCandidate,
    configured_ticker_and_request_budget,
    daily_ticker_limit,
    is_etf,
    plan_backfill,
)

TODAY = date(2026, 10, 6)
HKT = ZoneInfo("Asia/Hong_Kong")


def _utc(y, m, d, hh=0, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def _candidate(
    ticker: str,
    *,
    is_etf: bool = False,
    has_snapshot: bool = False,
    fetched_at: datetime | None = None,
    checked_at: datetime | None = None,
) -> BackfillCandidate:
    return BackfillCandidate(
        ticker=ticker,
        is_etf=is_etf,
        has_snapshot=has_snapshot,
        fetched_at=fetched_at,
        checked_at=checked_at,
    )


def test_etf_classification_covers_holdings_and_quote_type():
    assert is_etf("ETF") is True
    assert is_etf("etfs") is True
    assert is_etf("STK") is False
    assert is_etf("STK", "ETF") is False
    assert is_etf(None, "ETF") is True
    assert is_etf(None, "etn") is True
    assert is_etf(None, "EQUITY") is False
    assert is_etf(None, None) is False


def test_plan_skips_etf_classified_symbols():
    plan = plan_backfill(
        [
            _candidate("AAPL"),
            _candidate("QQQM", is_etf=True),
            _candidate("ICLN", is_etf=True),
            _candidate("IDEF", is_etf=True),
            _candidate("ARKK", is_etf=True),
        ],
        today=TODAY,
        limit=6,
    )
    assert plan.selected == ["AAPL"]
    assert plan.skipped_etfs == ["ARKK", "ICLN", "IDEF", "QQQM"]


def test_missing_snapshots_are_chosen_before_stale_ones():
    plan = plan_backfill(
        [
            _candidate(
                "NVDA",
                has_snapshot=True,
                fetched_at=_utc(2020, 1, 1),
                checked_at=_utc(2020, 1, 1),
            ),
            _candidate("MSFT"),
            _candidate("AAPL"),
        ],
        today=TODAY,
        limit=2,
    )
    assert plan.selected == ["AAPL", "MSFT"]


def test_stale_checked_names_rotate_ahead_of_recently_checked_ones():
    plan = plan_backfill(
        [
            _candidate(
                "NVDA",
                has_snapshot=True,
                fetched_at=_utc(2026, 9, 1),
                checked_at=_utc(2026, 10, 5),
            ),
            _candidate(
                "AAPL",
                has_snapshot=True,
                fetched_at=_utc(2026, 8, 1),
                checked_at=_utc(2026, 8, 1),
            ),
            _candidate(
                "MSFT",
                has_snapshot=True,
                fetched_at=_utc(2026, 9, 15),
                checked_at=_utc(2026, 9, 20),
            ),
        ],
        today=TODAY,
        limit=2,
    )
    assert plan.selected == ["AAPL", "MSFT"]


def test_names_already_touched_today_do_not_consume_another_batch():
    touched = [
        _candidate(
            symbol,
            has_snapshot=True,
            fetched_at=_utc(2026, 10, 6, 1),
            checked_at=_utc(2026, 10, 6, 1),
        )
        for symbol in ("AAPL", "AMD", "AMZN", "CRWD", "GOOGL", "META")
    ]
    plan = plan_backfill(
        touched + [_candidate("NVDA"), _candidate("QQQM", is_etf=True)],
        today=TODAY,
        limit=6,
    )
    assert plan.used_today == 6
    assert plan.selected == []
    assert plan.skipped_etfs == ["QQQM"]


def test_hkt_day_counts_a_late_utc_fetch_as_already_used():
    # 2026-10-05 20:00 UTC is 2026-10-06 04:00 in Asia/Hong_Kong.
    plan = plan_backfill(
        [
            _candidate(
                "AAPL",
                has_snapshot=True,
                fetched_at=_utc(2026, 10, 5, 20),
                checked_at=_utc(2026, 10, 5, 20),
            ),
            _candidate("MSFT"),
        ],
        today=date(2026, 10, 6),
        limit=6,
        tz=HKT,
    )
    assert plan.used_today == 1
    assert plan.selected == ["MSFT"]


def test_default_call_budget_is_six_tickers():
    assert DEFAULT_DAILY_TICKERS == 6
    assert DEFAULT_DAILY_REQUESTS == 24
    assert daily_ticker_limit(DEFAULT_DAILY_TICKERS, DEFAULT_DAILY_REQUESTS) == 6
    assert daily_ticker_limit(6, 25) == 6


def test_request_budget_of_20_selects_five_tickers():
    assert daily_ticker_limit(6, 20) == 5
    missing = [_candidate(symbol) for symbol in ("AAPL", "AMD", "AMZN", "CRWD", "GOOGL", "META", "NVDA")]
    plan = plan_backfill(missing, today=TODAY, limit=daily_ticker_limit(6, 20))
    assert plan.selected == ["AAPL", "AMD", "AMZN", "CRWD", "GOOGL"]


def test_ticker_limit_of_five_is_respected():
    missing = [_candidate(f"T{i:02d}") for i in range(8)]
    plan = plan_backfill(missing, today=TODAY, limit=daily_ticker_limit(5, 24))
    assert plan.selected == ["T00", "T01", "T02", "T03", "T04"]
    assert plan.limit == 5


def test_configured_limits_read_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AV_BACKFILL_DAILY_TICKERS", "5")
    monkeypatch.setenv("AV_BACKFILL_DAILY_REQUESTS", "20")
    assert configured_ticker_and_request_budget() == (5, 20)
    assert daily_ticker_limit(*configured_ticker_and_request_budget()) == 5


def test_invalid_limit_env_falls_back(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AV_BACKFILL_DAILY_TICKERS", "nope")
    monkeypatch.delenv("AV_BACKFILL_DAILY_REQUESTS", raising=False)
    assert configured_ticker_and_request_budget() == (DEFAULT_DAILY_TICKERS, DEFAULT_DAILY_REQUESTS)


def test_backfill_workflow_is_manual_only():
    text = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "av-fundamentals-backfill.yml"
    ).read_text()
    assert "workflow_dispatch:" in text
    assert 'default: "true"' in text
    for line in text.splitlines():
        stripped = line.strip()
        assert not stripped.startswith("schedule:")
        assert "cron:" not in stripped
