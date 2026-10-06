"""Alpha Vantage rate-limit logs must not include the API key."""
import logging
from unittest.mock import MagicMock, patch

from scraper.alpha_vantage_scraper import AlphaVantageClient, redact_av_secrets
from utils.logger import logger


def test_redact_av_secrets_strips_key_and_query_param():
    text = "rate limit for apikey=SECRETKEY123 url=https://x?apikey=SECRETKEY123"
    safe = redact_av_secrets(text, "SECRETKEY123")
    assert "SECRETKEY123" not in safe
    assert "apikey=[REDACTED]" in safe


def _capture(fn):
    messages: list[str] = []

    class _Handler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            messages.append(record.getMessage())

    handler = _Handler()
    logger.addHandler(handler)
    try:
        result = fn()
    finally:
        logger.removeHandler(handler)
    return result, messages


def test_rate_limit_log_and_payload_redact_api_key():
    client = AlphaVantageClient(api_key="SECRETKEY123")
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "Note": "Thank you for using Alpha Vantage. API rate limit for apikey=SECRETKEY123",
    }

    def run():
        with patch.object(client, "_rate_limit"), patch(
            "scraper.alpha_vantage_scraper.requests.get", return_value=response
        ):
            return client._fetch({"function": "OVERVIEW", "symbol": "NVDA"})

    result, messages = _capture(run)
    blob = " ".join(messages) + str(result)
    assert "SECRETKEY123" not in blob
    assert result["_error"] == "rate_limit"
    assert "apikey=[REDACTED]" in result["_message"]


def test_request_exception_log_redacts_api_key():
    client = AlphaVantageClient(api_key="SECRETKEY123")

    def run():
        with patch.object(client, "_rate_limit"), patch(
            "scraper.alpha_vantage_scraper.requests.get",
            side_effect=RuntimeError(
                "GET https://www.alphavantage.co/query?function=OVERVIEW&apikey=SECRETKEY123 failed"
            ),
        ):
            return client._fetch({"function": "OVERVIEW"})

    result, messages = _capture(run)
    blob = " ".join(messages) + result["_error"]
    assert "SECRETKEY123" not in blob
    assert "apikey=[REDACTED]" in result["_error"]
