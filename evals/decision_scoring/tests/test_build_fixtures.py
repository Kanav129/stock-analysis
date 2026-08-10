import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from evals.decision_scoring import build_fixtures


@patch("evals.decision_scoring.build_fixtures.portfolio_markdown_for")
@patch("evals.decision_scoring.build_fixtures.ReportService")
def test_build_ticker_fixture_uses_latest_core_report(mock_report_service, mock_portfolio):
    mock_report_service.return_value.get_latest_report.return_value = {
        "id": 42,
        "sections": {"fundamentals": "## Fundamentals\nStrong cash flow."},
        "factor_scores": {"quality": 8},
        "live_price": 101.25,
        "rating": {"rating": "BUY"},
    }
    mock_portfolio.return_value = "## Personal Portfolio\n- Not held."

    fixture = build_fixtures.build_ticker_fixture("aapl")

    assert fixture == {
        "ticker": "AAPL",
        "report_id": 42,
        "live_price": 101.25,
        "factor_scores": {"quality": 8},
        "sections_markdown": {
            "fundamentals": "## Fundamentals\nStrong cash flow."
        },
        "portfolio_markdown": "## Personal Portfolio\n- Not held.",
    }
    mock_report_service.return_value.get_latest_report.assert_called_once_with(
        "AAPL", "core"
    )
    mock_portfolio.assert_called_once_with("AAPL")


@patch("evals.decision_scoring.build_fixtures.ReportService")
def test_build_ticker_fixture_rejects_missing_report(mock_report_service):
    mock_report_service.return_value.get_latest_report.return_value = None

    with pytest.raises(LookupError, match="AAPL"):
        build_fixtures.build_ticker_fixture("AAPL")


@patch("evals.decision_scoring.build_fixtures.FinnhubClient")
@patch("evals.decision_scoring.build_fixtures.yf.Ticker")
def test_build_street_gold_uses_yfinance_and_latest_finnhub_period(
    mock_yf_ticker, mock_finnhub_client
):
    stock = MagicMock()
    stock.info = {
        "recommendationKey": "buy",
        "recommendationMean": 2.1,
        "targetMeanPrice": 125.5,
        "currentPrice": 110.0,
        "numberOfAnalystOpinions": 30,
    }
    mock_yf_ticker.return_value = stock
    mock_finnhub_client.return_value.get_recommendation_trends.return_value = [
        {
            "period": "2026-06-01",
            "strongBuy": 8,
            "buy": 12,
            "hold": 5,
            "sell": 1,
            "strongSell": 0,
            "symbol": "AAPL",
        },
        {
            "period": "2026-07-01",
            "strongBuy": 10,
            "buy": 13,
            "hold": 4,
            "sell": 1,
            "strongSell": 0,
            "symbol": "AAPL",
        },
    ]

    result = build_fixtures.build_street_gold(["aapl"])

    assert result["as_of"].endswith("+00:00")
    assert result["tickers"]["AAPL"] == {
        "recommendation_key": "buy",
        "recommendation_mean": 2.1,
        "target_mean": 125.5,
        "price": 110.0,
        "n_analysts": 30,
        "finnhub_rec": {
            "strongBuy": 10,
            "buy": 13,
            "hold": 4,
            "sell": 1,
            "strongSell": 0,
        },
    }


@patch("evals.decision_scoring.build_fixtures.build_street_gold")
@patch("evals.decision_scoring.build_fixtures.build_ticker_fixture")
def test_write_fixtures_writes_tickers_and_street_gold(
    mock_build_ticker, mock_build_street, tmp_path: Path
):
    mock_build_ticker.side_effect = lambda ticker: {
        "ticker": ticker,
        "sections_markdown": {"summary": ticker},
    }
    mock_build_street.return_value = {
        "as_of": "2026-08-10T00:00:00+00:00",
        "tickers": {},
    }

    build_fixtures.write_fixtures(["aapl", "DIS"], tmp_path)

    assert json.loads((tmp_path / "AAPL.json").read_text())["ticker"] == "AAPL"
    assert json.loads((tmp_path / "DIS.json").read_text())["ticker"] == "DIS"
    assert json.loads((tmp_path / "street_gold.json").read_text()) == {
        "as_of": "2026-08-10T00:00:00+00:00",
        "tickers": {},
    }
