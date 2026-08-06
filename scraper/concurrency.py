"""Shared sync concurrency helpers."""
from __future__ import annotations

import os


def sync_max_concurrent() -> int:
    raw = os.getenv("SYNC_MAX_CONCURRENT", "1")
    try:
        return max(1, int(raw))
    except ValueError:
        return 1
