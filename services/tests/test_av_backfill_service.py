"""Drip service plans from the universe and does not call Alpha Vantage on a dry run."""
from datetime import datetime, timezone

from services.av_backfill_service import AvBackfillService

NOW = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)


class _Universe:
    def __init__(self, tickers: list[str]) -> None:
        self._tickers = tickers

    def get_tickers(self) -> list[str]:
        return list(self._tickers)


class _Holdings:
    def __init__(self, assets: dict[str, str]) -> None:
        self._assets = assets

    def current_asset_classes(self) -> dict[str, str]:
        return dict(self._assets)


class _Store:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows or []

    def list_status(self) -> list[dict]:
        return list(self.rows)


class _Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.requests_made = 0
        self.rate_limited = False

    def get_financial_snapshot(self, ticker: str, **kwargs):
        self.calls.append((ticker, kwargs))
        self.requests_made += 4
        if ticker == "NVDA":
            self.rate_limited = True
            return {"errors": {"income": "rate_limit"}}
        return {"overview": {}, "errors": {}}


def _service(client: _Client | None = None, **kwargs) -> AvBackfillService:
    return AvBackfillService(
        universe=_Universe(["QQQM", "aapl", "ICLN", "IDEF", "MSFT", "NVDA", "ARKK"]),
        holdings=_Holdings(
            {
                "AAPL": "STK",
                "QQQM": "ETF",
                "ICLN": "ETF",
                "IDEF": "ETF",
                "MSFT": "STK",
                "NVDA": "STK",
            }
        ),
        store=_Store(
            [
                {
                    "ticker": "NVDA",
                    "fetched_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
                    "checked_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
                }
            ]
        ),
        client=client,
        quote_types={"ARKK": "ETF"},
        quote_type_lookup=lambda ticker: (_ for _ in ()).throw(AssertionError(ticker)),
        tz=timezone.utc,
        daily_tickers=6,
        daily_requests=24,
        **kwargs,
    )


def test_dry_run_skips_etfs_and_does_not_call_alpha_vantage():
    client = _Client()
    result = _service(client).run(dry_run=True, now=NOW)
    assert result["dry_run"] is True
    assert result["requests_made"] == 0
    assert client.calls == []
    assert result["skipped_etfs"] == ["ARKK", "ICLN", "IDEF", "QQQM"]
    # Missing equities before the stale NVDA snapshot. Budget is 6; only 3 equities.
    assert result["selected"] == ["AAPL", "MSFT", "NVDA"]
    assert result["refreshed"] == []


def test_run_refreshes_missing_names_and_stops_on_rate_limit(monkeypatch):
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    client = _Client()
    result = _service(client).run(dry_run=False, now=NOW)
    assert [ticker for ticker, _ in client.calls] == ["AAPL", "MSFT", "NVDA"]
    assert client.calls[0][1]["refresh"] is True
    assert client.calls[0][1]["mark_checked"] is True
    assert result["refreshed"] == ["AAPL", "MSFT"]
    assert result["errors"] == [{"ticker": "NVDA", "error": "rate_limit"}]
    assert result["requests_made"] == 12
    assert "QQQM" not in result["refreshed"]


def test_second_run_same_day_does_not_call_alpha_vantage_again():
    """A finished batch is checked today, so a rerun must not spend more calls."""
    from unittest.mock import patch

    from scraper.alpha_vantage_scraper import AlphaVantageClient

    class _MemoryStore:
        def __init__(self) -> None:
            self.rows: dict[str, dict] = {}

        def list_status(self) -> list[dict]:
            return [
                {
                    "ticker": ticker,
                    "fetched_at": row["fetched_at"],
                    "checked_at": row["checked_at"],
                }
                for ticker, row in self.rows.items()
            ]

        def load(self, ticker: str):
            return self.rows.get(ticker.upper())

        def save(self, ticker: str, **kwargs):
            symbol = ticker.upper()
            self.rows[symbol] = {"ticker": symbol, **kwargs}

    calls: list[str] = []

    def _fetch(params: dict) -> dict:
        calls.append(str(params.get("symbol")))
        client.requests_made += 1
        if params.get("function") == "INCOME_STATEMENT":
            return {
                "quarterlyReports": [{"fiscalDateEnding": "2026-06-30", "totalRevenue": "10"}],
                "annualReports": [],
            }
        if params.get("function") == "OVERVIEW":
            return {"Sector": "Technology"}
        return {"quarterlyReports": [], "annualReports": []}

    store = _MemoryStore()
    with (
        patch("scraper.alpha_vantage_scraper.CACHE_DIR") as cache_dir,
        patch("scraper.alpha_vantage_scraper.lookup_reported_earnings", return_value=None),
    ):
        cache_dir.mkdir.return_value = None
        client = AlphaVantageClient(api_key="test-not-real")
        client._fetch = _fetch  # type: ignore[method-assign]
        equities = ["AAPL", "AMD", "AMZN", "CRWD", "GOOGL", "META"]
        service = AvBackfillService(
            universe=_Universe(equities + ["QQQM", "ICLN", "IDEF"]),
            holdings=_Holdings(
                {
                    **{symbol: "STK" for symbol in equities},
                    "QQQM": "ETF",
                    "ICLN": "ETF",
                    "IDEF": "ETF",
                }
            ),
            store=store,
            client=client,
            quote_types={},
            tz=timezone.utc,
            daily_tickers=6,
            daily_requests=24,
        )
        first = service.run(dry_run=False, now=NOW)
        second = service.run(dry_run=False, now=NOW)

    assert first["selected"] == equities
    assert first["skipped_etfs"] == ["ICLN", "IDEF", "QQQM"]
    assert first["refreshed"] == equities
    assert first["requests_made"] == 24
    assert len(calls) == 24
    assert set(calls) == set(equities)
    assert second["selected"] == []
    assert second["reason"] == "daily_limit_reached"
    assert second["requests_made"] == 0
    assert len(calls) == 24


def test_live_run_without_a_key_does_not_call_alpha_vantage(monkeypatch):
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    result = _service(client=None).run(dry_run=False, now=NOW)
    assert result["reason"] == "missing_api_key"
    assert result["requests_made"] == 0
    assert result["selected"] == ["AAPL", "MSFT", "NVDA"]
