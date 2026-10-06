"""Compose the post-weekly note from stored ratings and watchlist suggestions.

The watchlist section copies `reason` from `watchlist_suggestions`. It does not
invent tickers or rewrite catalysts.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services import run_checkpoint_service as rcs
from utils.logger import logger

WATCHLIST_SECTION_TITLE = "Watchlist adds to consider"
EMPTY_WATCHLIST_LINE = "No model watchlist suggestions this week"
REASON_MAX_CHARS = 140
MAX_WATCHLIST_ADDS = 8

_BUY_RATINGS = frozenset({"BUY", "STRONG_BUY"})
_SELL_RATINGS = frozenset({"SELL", "STRONG_SELL"})


def truncate_stored_reason(reason: str, limit: int = REASON_MAX_CHARS) -> str:
    text = reason.strip()
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1].rstrip() + "…"


def watchlist_add_lines(
    suggestions: list[dict[str, Any]],
    *,
    holdings: list[str],
    watchlist: list[str],
    limit: int = MAX_WATCHLIST_ADDS,
) -> list[tuple[str, str]]:
    excluded = {str(ticker).upper() for ticker in holdings}
    excluded.update(str(ticker).upper() for ticker in watchlist)
    lines: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in suggestions:
        ticker = str(item.get("ticker") or "").upper().strip()
        raw_reason = item.get("reason")
        if raw_reason is None:
            continue
        reason = str(raw_reason).strip()
        if not ticker or not reason or ticker in excluded or ticker in seen:
            continue
        seen.add(ticker)
        lines.append((ticker, truncate_stored_reason(reason)))
        if len(lines) >= limit:
            break
    return lines


def _score_label(score: Any) -> str:
    value = int(score)
    if value > 0:
        return f"+{value}"
    return str(value)


def _call_lines(completed: list[dict[str, Any]], ratings: frozenset[str], *, sell: bool) -> list[str]:
    rows: list[tuple[int, str, str, str]] = []
    for item in completed:
        ticker = str(item.get("ticker") or "").upper().strip()
        rating = str(item.get("rating") or "").upper().strip()
        if not ticker or rating not in ratings or item.get("score") is None:
            continue
        score = int(item["score"])
        rows.append((score, ticker, rating, _score_label(score)))
    if sell:
        rows.sort(key=lambda row: (row[0], row[1]))
    else:
        rows.sort(key=lambda row: (-row[0], row[1]))
    return [f"- {ticker} {rating} {label}" for _score, ticker, rating, label in rows]


def format_watchlist_adds_section(lines: list[tuple[str, str]]) -> str:
    if not lines:
        body = EMPTY_WATCHLIST_LINE
    else:
        body = "\n".join(f"- {ticker} — {reason}" for ticker, reason in lines)
    return f"{WATCHLIST_SECTION_TITLE}\n{body}"


def format_weekly_summary(
    completed: list[dict[str, Any]],
    watchlist_lines: list[tuple[str, str]],
) -> str:
    parts = ["Weekly summary"]
    buys = _call_lines(completed, _BUY_RATINGS, sell=False)
    sells = _call_lines(completed, _SELL_RATINGS, sell=True)
    if buys:
        parts.append("Top buys\n" + "\n".join(buys))
    if sells:
        parts.append("Top sells\n" + "\n".join(sells))
    parts.append(format_watchlist_adds_section(watchlist_lines))
    return "\n\n".join(parts)


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def suggestions_are_stale(items: list[dict[str, Any]], *, day: str) -> bool:
    """True when nothing active was written on this analysis day."""
    if not items:
        return True
    start, _end = rcs.day_bounds_utc(day)
    newest: datetime | None = None
    for item in items:
        ts = _parse_ts(item.get("suggested_at"))
        if ts is None:
            continue
        if newest is None or ts > newest:
            newest = ts
    if newest is None:
        return True
    return newest < start


def compose_post_weekly_summary(
    completed: list[dict[str, Any]],
    *,
    day: str,
    suggestions: Any | None = None,
    universe: Any | None = None,
    idea_scan: Any | None = None,
) -> str:
    """Build the note. Refresh a stale idea scan, then read stored rows only."""
    if suggestions is None:
        from services.suggestion_service import SuggestionService

        suggestions = SuggestionService()
    if universe is None:
        from services.universe_service import UniverseService

        universe = UniverseService()

    items = list(suggestions.list_active() or [])
    if suggestions_are_stale(items, day=day):
        scan = idea_scan
        if scan is None:
            from services.idea_scan_service import IdeaScanService

            scan = IdeaScanService()
        try:
            scan.rebuild()
        except Exception as exc:
            logger.error("Weekly idea-scan refresh failed: %s", exc)
        items = list(suggestions.list_active() or [])

    detail = universe.get_universe_detail() or {}
    lines = watchlist_add_lines(
        items,
        holdings=list(detail.get("holdings") or []),
        watchlist=list(detail.get("watchlist") or []),
    )
    return format_weekly_summary(list(completed or []), lines)
