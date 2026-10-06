"""Yahoo fundamentals health: crumb, empty info, and null fields count as down."""
import logging

from scraper.yahoo_health import (
    SAMPLE_SIZE,
    classify_yahoo_info,
    equity_probe_sample,
    read_yahoo_fundamentals,
    yahoo_sample_is_failing,
)


def test_invalid_crumb_empty_info_and_null_fields_are_failures():
    assert classify_yahoo_info(None, RuntimeError("Invalid Crumb")) == "invalid_crumb"
    assert classify_yahoo_info({}) == "empty"
    assert classify_yahoo_info(None) == "empty"
    assert (
        classify_yahoo_info(
            {
                "trailingPE": None,
                "forwardPE": None,
                "beta": None,
                "grossMargins": None,
                "revenueGrowth": None,
            }
        )
        == "null_fields"
    )
    assert classify_yahoo_info({"beta": float("nan"), "trailingPE": "n/a"}) == "null_fields"


def test_a_real_fundamental_field_is_healthy():
    assert classify_yahoo_info({"trailingPE": 28.5}) == "ok"
    assert classify_yahoo_info({"revenueGrowth": 0.12}) == "ok"
    assert classify_yahoo_info({"grossMargins": 0}) == "ok"


def test_sample_fails_only_when_every_probed_ticker_is_down():
    assert yahoo_sample_is_failing(["invalid_crumb", "empty", "null_fields"]) is True
    assert yahoo_sample_is_failing(["null_fields", "ok"]) is False
    assert yahoo_sample_is_failing([]) is False


def test_probe_sample_prefers_liquid_equities_and_skips_etfs():
    sample = equity_probe_sample(
        ["QQQM", "ARKK", "ZZZ", "NVDA", "AAPL", "MSFT", "BBB"],
        etfs={"QQQM", "ARKK"},
    )
    assert sample == ["AAPL", "MSFT", "NVDA"]
    assert len(sample) <= SAMPLE_SIZE


def test_crumb_probe_does_not_log_the_exception_text():
    secret = "SECRETKEY123"

    def load():
        raise RuntimeError(f"Invalid Crumb apikey={secret} https://query1.finance.yahoo.com")

    logger = logging.getLogger("scraper.yahoo_health")
    messages: list[str] = []

    class _Handler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            messages.append(record.getMessage())

    handler = _Handler()
    logger.addHandler(handler)
    try:
        status = read_yahoo_fundamentals(load)
    finally:
        logger.removeHandler(handler)
    assert status == "invalid_crumb"
    assert secret not in " ".join(messages)
