"""Global live price refresh gate — pause on Yahoo rate limits."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

# Yahoo asks to "try after a while"; 15m avoids hammering while RTH continues.
PAUSE_SECONDS = 15 * 60


def is_yahoo_rate_limit(exc: Exception | str) -> bool:
    msg = str(exc).lower()
    return "rate limit" in msg or "too many requests" in msg


class LiveRefreshService:
    def __init__(self) -> None:
        self._pause_until: float = 0.0
        self._lock = threading.Lock()
        self._running = False

    def is_paused(self) -> bool:
        return time.time() < self._pause_until

    def pause_until_ts(self) -> float | None:
        if self.is_paused():
            return self._pause_until
        return None

    def pause_until_iso(self) -> str | None:
        ts = self.pause_until_ts()
        if ts is None:
            return None
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    def record_rate_limit(self) -> str:
        """Extend pause window and return ISO pause_until."""
        until = time.time() + PAUSE_SECONDS
        self._pause_until = max(self._pause_until, until)
        return datetime.fromtimestamp(self._pause_until, tz=timezone.utc).isoformat()

    def try_begin(self) -> bool:
        with self._lock:
            if self._running:
                return False
            self._running = True
            return True

    def end(self) -> None:
        with self._lock:
            self._running = False


live_refresh_service = LiveRefreshService()
