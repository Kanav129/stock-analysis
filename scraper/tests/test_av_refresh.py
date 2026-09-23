"""When to spend an Alpha Vantage fundamentals call."""
from datetime import date, datetime, timezone
from unittest.mock import patch

from scraper.alpha_vantage_scraper import lookup_reported_earnings
from scraper.av_refresh import (
    latest_fiscal_date,
    reported_earnings_at,
    should_refresh_fundamentals,
)


def _utc(y, m, d, hh=0, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def test_refresh_when_nothing_is_saved():
    assert should_refresh_fundamentals(
        fetched_at=None,
        checked_at=None,
        reported_earnings_at=_utc(2026, 7, 24),
        now=_utc(2026, 9, 23),
    )


def test_reuse_when_no_earnings_date_is_known():
    assert not should_refresh_fundamentals(
        fetched_at=_utc(2026, 7, 25),
        checked_at=_utc(2026, 7, 25),
        reported_earnings_at=None,
        now=_utc(2026, 9, 23),
    )


def test_reuse_when_last_print_is_already_in_the_snapshot():
    assert not should_refresh_fundamentals(
        fetched_at=_utc(2026, 7, 25, 12),
        checked_at=_utc(2026, 7, 25, 12),
        reported_earnings_at=_utc(2026, 7, 24, 20),
        now=_utc(2026, 9, 23),
    )


def test_refresh_when_a_print_landed_after_the_save():
    assert should_refresh_fundamentals(
        fetched_at=_utc(2026, 7, 25),
        checked_at=_utc(2026, 7, 25),
        reported_earnings_at=_utc(2026, 9, 22, 21),
        now=_utc(2026, 9, 23, 10),
    )


def test_skip_a_second_check_on_the_same_day_if_the_filing_has_not_advanced():
    assert not should_refresh_fundamentals(
        fetched_at=_utc(2026, 7, 25),
        checked_at=_utc(2026, 9, 23, 8),
        reported_earnings_at=_utc(2026, 9, 22, 21),
        now=_utc(2026, 9, 23, 18),
    )


def test_retry_the_next_day_if_the_filing_still_has_not_advanced():
    assert should_refresh_fundamentals(
        fetched_at=_utc(2026, 7, 25),
        checked_at=_utc(2026, 9, 22, 22),
        reported_earnings_at=_utc(2026, 9, 22, 21),
        now=_utc(2026, 9, 23, 10),
    )


def test_latest_fiscal_date_uses_the_newest_statement_period():
    snapshot = {
        "income_quarterly": [
            {"fiscalDateEnding": "2026-06-30"},
            {"fiscalDateEnding": "2026-03-31"},
        ],
        "income_annual": [{"fiscalDateEnding": "2025-12-31"}],
    }
    assert latest_fiscal_date(snapshot) == date(2026, 6, 30)


def test_latest_fiscal_date_is_none_without_statements():
    assert latest_fiscal_date({"income_quarterly": [], "overview": {}}) is None


def test_reported_earnings_ignores_future_estimates():
    class Frame:
        index = [_utc(2026, 10, 29), _utc(2026, 7, 30)]
        columns = {"Reported EPS": [None, 1.35]}

        def __getitem__(self, key):
            return self.columns[key]

    found = reported_earnings_at(Frame(), calendar=None, now=_utc(2026, 9, 23))
    assert found == _utc(2026, 7, 30)


def test_reported_earnings_uses_a_past_calendar_date_when_history_is_missing():
    found = reported_earnings_at(
        None,
        calendar={"Earnings Date": "2026-09-22"},
        now=_utc(2026, 9, 23),
    )
    assert found == _utc(2026, 9, 22)


def test_reported_earnings_ignores_a_future_calendar_date():
    found = reported_earnings_at(
        None,
        calendar={"Earnings Date": "2026-10-29"},
        now=_utc(2026, 9, 23),
    )
    assert found is None


def test_lookup_falls_back_to_calendar_when_earnings_history_fails():
    class Stock:
        @property
        def earnings_dates(self):
            raise ImportError("Import lxml failed")

        @property
        def calendar(self):
            return {"Earnings Date": "2020-01-15"}

    with patch("scraper.yf_cache.get_yf_ticker", return_value=Stock()):
        found = lookup_reported_earnings("MAR")
    assert found == _utc(2020, 1, 15)


def test_naive_datetimes_compare_as_utc():
    assert not should_refresh_fundamentals(
        fetched_at=datetime(2026, 7, 25, 12, 0),
        checked_at=datetime(2026, 7, 25, 12, 0),
        reported_earnings_at=datetime(2026, 7, 24, 20, 0),
        now=datetime(2026, 9, 23),
    )
