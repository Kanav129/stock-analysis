import time

from services.live_refresh_service import (
    LiveRefreshService,
    is_yahoo_rate_limit,
    live_refresh_service,
)


def test_is_yahoo_rate_limit():
    assert is_yahoo_rate_limit("Too Many Requests. Rate limited. Try after a while.")
    assert is_yahoo_rate_limit(Exception("HTTP 429: rate limit exceeded"))
    assert not is_yahoo_rate_limit("connection timeout")


def test_pause_on_rate_limit():
    svc = LiveRefreshService()
    assert not svc.is_paused()

    iso = svc.record_rate_limit()
    assert svc.is_paused()
    assert svc.pause_until_iso() == iso
    assert svc.pause_until_ts() is not None


def test_pause_extends_on_repeat():
    svc = LiveRefreshService()
    first = svc.record_rate_limit()
    time.sleep(0.01)
    svc._pause_until -= 60  # simulate partial elapsed window
    second = svc.record_rate_limit()
    assert second >= first


def test_try_begin_blocks_overlap():
    svc = LiveRefreshService()
    assert svc.try_begin()
    assert not svc.try_begin()
    svc.end()
    assert svc.try_begin()
    svc.end()


def test_module_singleton():
    assert live_refresh_service.try_begin()
    live_refresh_service.end()
