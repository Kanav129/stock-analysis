from unittest.mock import MagicMock, patch

import requests

from scraper.finnhub_scraper import FinnhubClient


def test_get_price_target_403_returns_empty_without_raising():
    client = FinnhubClient(api_key="test")
    resp = MagicMock()
    resp.status_code = 403
    err = requests.HTTPError("403 Client Error: Forbidden", response=resp)
    resp.raise_for_status.side_effect = err
    with patch("scraper.finnhub_scraper.requests.get", return_value=resp):
        with patch("scraper.finnhub_scraper.logger") as log:
            out = client.get_price_target("GOOGL")
    assert out == {}
    # Premium/forbidden endpoints should not scream ERROR.
    assert log.error.call_count == 0
    assert log.warning.call_count >= 1


def test_get_price_target_logs_info_only_when_data_present():
    client = FinnhubClient(api_key="test")
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"targetMean": 200.0}
    with patch("scraper.finnhub_scraper.requests.get", return_value=resp):
        with patch("scraper.finnhub_scraper.logger") as log:
            out = client.get_price_target("AAPL")
    assert out["targetMean"] == 200.0
    log.info.assert_called()
