"""Persisted Alpha Vantage snapshots are reused until a new earnings print."""
from datetime import datetime, timezone
from unittest.mock import patch

from scraper.alpha_vantage_scraper import AlphaVantageClient


def _utc(y, m, d, hh=0, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def _snapshot(fiscal: str, revenue: str = "100") -> dict:
    return {
        "overview": {"sector": "Technology", "market_cap": "1"},
        "income_annual": [{"fiscalDateEnding": "2025-12-31", "totalRevenue": revenue}],
        "income_quarterly": [{"fiscalDateEnding": fiscal, "totalRevenue": revenue}],
        "balance_annual": [],
        "balance_quarterly": [],
        "cashflow_annual": [],
        "cashflow_quarterly": [],
        "errors": {},
    }


class _Store:
    def __init__(self, row=None):
        self.row = row
        self.saved = None

    def load(self, ticker: str):
        return self.row

    def save(self, ticker: str, **kwargs):
        self.saved = {"ticker": ticker, **kwargs}
        self.row = {
            "snapshot": kwargs["snapshot"],
            "fiscal_date_ending": kwargs["fiscal_date_ending"],
            "fetched_at": kwargs["fetched_at"],
            "checked_at": kwargs["checked_at"],
        }


def _client():
    with patch("scraper.alpha_vantage_scraper.CACHE_DIR") as cache_dir:
        cache_dir.mkdir.return_value = None
        return AlphaVantageClient(api_key="test")


def test_reuses_saved_snapshot_without_calling_alpha_vantage():
    stored = _snapshot("2026-06-30")
    store = _Store(
        {
            "snapshot": stored,
            "fiscal_date_ending": "2026-06-30",
            "fetched_at": _utc(2026, 7, 25),
            "checked_at": _utc(2026, 7, 25),
        }
    )
    client = _client()
    with (
        patch.object(client, "_fetch", side_effect=AssertionError("should not call AV")),
        patch(
            "scraper.alpha_vantage_scraper.lookup_reported_earnings",
            return_value=_utc(2026, 7, 24),
        ),
    ):
        out = client.get_financial_snapshot("AAPL", store=store, now=_utc(2026, 9, 23))
    assert out["income_quarterly"][0]["fiscalDateEnding"] == "2026-06-30"
    assert store.saved is None


def test_first_save_ignores_a_stale_disk_cache():
    store = _Store()
    client = _client()
    stale = {
        "quarterlyReports": [{"fiscalDateEnding": "2025-06-30", "totalRevenue": "1"}],
        "annualReports": [],
    }
    with (
        patch.object(client, "_read_cache", return_value=stale),
        patch.object(client, "_write_cache"),
        patch.object(client, "_fetch", side_effect=_raw_statements("2026-06-30", "100")) as fetch,
        patch(
            "scraper.alpha_vantage_scraper.lookup_reported_earnings",
            return_value=_utc(2026, 7, 24),
        ),
    ):
        out = client.get_financial_snapshot("AAPL", store=store, now=_utc(2026, 9, 23))
    assert fetch.called
    assert out["income_quarterly"][0]["fiscalDateEnding"] == "2026-06-30"


def test_fetches_and_saves_when_nothing_is_stored():
    store = _Store()
    client = _client()
    fresh = _raw_statements("2026-06-30")
    with (
        patch.object(client, "_read_cache", return_value=None),
        patch.object(client, "_write_cache"),
        patch.object(client, "_fetch", side_effect=fresh),
        patch(
            "scraper.alpha_vantage_scraper.lookup_reported_earnings",
            return_value=None,
        ),
    ):
        out = client.get_financial_snapshot("AAPL", store=store, now=_utc(2026, 9, 23))
    assert out["income_quarterly"][0]["fiscalDateEnding"] == "2026-06-30"
    assert store.saved["ticker"] == "AAPL"
    assert store.saved["fiscal_date_ending"].isoformat() == "2026-06-30"
    assert store.saved["fetched_at"] == _utc(2026, 9, 23)


def test_refetches_after_a_new_earnings_print_and_replaces_the_snapshot():
    store = _Store(
        {
            "snapshot": _snapshot("2026-06-30", "100"),
            "fiscal_date_ending": "2026-06-30",
            "fetched_at": _utc(2026, 7, 25),
            "checked_at": _utc(2026, 7, 25),
        }
    )
    client = _client()
    with (
        patch.object(client, "_read_cache", return_value=None),
        patch.object(client, "_write_cache"),
        patch.object(client, "_fetch", side_effect=_raw_statements("2026-09-30", "140")),
        patch(
            "scraper.alpha_vantage_scraper.lookup_reported_earnings",
            return_value=_utc(2026, 9, 22, 21),
        ),
    ):
        out = client.get_financial_snapshot("AAPL", store=store, now=_utc(2026, 9, 23, 10))
    assert out["income_quarterly"][0]["totalRevenue"] == "140"
    assert store.saved["fiscal_date_ending"].isoformat() == "2026-09-30"
    assert store.saved["fetched_at"] == _utc(2026, 9, 23, 10)


def test_keeps_saved_statements_when_the_new_filing_is_not_published_yet():
    old = _snapshot("2026-06-30", "100")
    store = _Store(
        {
            "snapshot": old,
            "fiscal_date_ending": "2026-06-30",
            "fetched_at": _utc(2026, 7, 25),
            "checked_at": _utc(2026, 7, 25),
        }
    )
    client = _client()
    with (
        patch.object(client, "_read_cache", return_value=None),
        patch.object(client, "_write_cache"),
        patch.object(client, "_fetch", side_effect=_raw_statements("2026-06-30", "100")) as fetch,
        patch(
            "scraper.alpha_vantage_scraper.lookup_reported_earnings",
            return_value=_utc(2026, 9, 22, 21),
        ),
    ):
        out = client.get_financial_snapshot("AAPL", store=store, now=_utc(2026, 9, 23, 10))
    assert fetch.called
    assert out == old
    assert store.saved["fetched_at"] == _utc(2026, 7, 25)
    assert store.saved["checked_at"] == _utc(2026, 9, 23, 10)
    assert store.saved["snapshot"] == old


def test_does_not_call_again_the_same_day_after_an_unchanged_filing():
    store = _Store(
        {
            "snapshot": _snapshot("2026-06-30"),
            "fiscal_date_ending": "2026-06-30",
            "fetched_at": _utc(2026, 7, 25),
            "checked_at": _utc(2026, 9, 23, 8),
        }
    )
    client = _client()
    with (
        patch.object(client, "_fetch", side_effect=AssertionError("should not call AV")),
        patch(
            "scraper.alpha_vantage_scraper.lookup_reported_earnings",
            return_value=_utc(2026, 9, 22, 21),
        ),
    ):
        out = client.get_financial_snapshot("AAPL", store=store, now=_utc(2026, 9, 23, 18))
    assert out["income_quarterly"][0]["fiscalDateEnding"] == "2026-06-30"
    assert store.saved is None


def _raw_statements(fiscal: str, revenue: str = "100"):
    income = {"quarterlyReports": [{"fiscalDateEnding": fiscal, "totalRevenue": revenue}], "annualReports": []}
    empty = {"quarterlyReports": [], "annualReports": []}
    overview = {"Sector": "Technology", "MarketCapitalization": "1"}

    def _side_effect(params):
        function = params.get("function")
        if function == "INCOME_STATEMENT":
            return income
        if function == "OVERVIEW":
            return overview
        return empty

    return _side_effect
