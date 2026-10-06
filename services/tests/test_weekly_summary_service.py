"""Weekly summary watchlist section uses stored suggestion reasons only."""
from datetime import datetime, timezone
from unittest.mock import MagicMock

from services.weekly_summary_service import (
    compose_post_weekly_summary,
    format_weekly_summary,
    suggestions_are_stale,
    watchlist_add_lines,
)


def test_empty_suggestions_say_none_this_week():
    note = format_weekly_summary([], [])

    assert "Watchlist adds to consider" in note
    assert "No model watchlist suggestions this week" in note
    assert "AAPL" not in note
    assert "because" not in note.lower()


def test_populated_list_uses_verbatim_stored_reasons():
    lines = watchlist_add_lines(
        [
            {
                "ticker": "nvda",
                "reason": "Export-license headlines put a near-term catalyst on the name.",
            },
            {
                "ticker": "AMD",
                "reason": "Peer mentions tie a data-center order to this week's tape.",
            },
        ],
        holdings=["AAPL"],
        watchlist=["MSFT"],
    )
    note = format_weekly_summary([], lines)

    assert "- NVDA — Export-license headlines put a near-term catalyst on the name." in note
    assert "- AMD — Peer mentions tie a data-center order to this week's tape." in note
    assert note.index("NVDA") < note.index("AMD")


def test_long_reason_is_truncated_without_rewriting():
    reason = "A" * 180
    lines = watchlist_add_lines(
        [{"ticker": "CRM", "reason": reason}],
        holdings=[],
        watchlist=[],
    )

    shown = lines[0][1]
    assert len(shown) == 140
    assert shown.startswith("A" * 139)
    assert shown.endswith("…")
    assert reason[:139] == shown[:139]


def test_excludes_holdings_and_watchlist_and_blank_reasons():
    lines = watchlist_add_lines(
        [
            {"ticker": "AAPL", "reason": "Already held — must not appear."},
            {"ticker": "MSFT", "reason": "Already on the watchlist."},
            {"ticker": "ORCL", "reason": "   "},
            {"ticker": "NOW", "reason": None},
            {"ticker": "SNOW", "reason": "Cloud billings guide was raised in the filing."},
        ],
        holdings=["aapl"],
        watchlist=["msft"],
    )

    tickers = [ticker for ticker, _reason in lines]
    assert tickers == ["SNOW"]
    assert lines[0][1] == "Cloud billings guide was raised in the filing."


def test_caps_at_eight_and_does_not_pad():
    suggestions = [
        {"ticker": f"T{i}", "reason": f"Stored reason {i}."}
        for i in range(10)
    ]
    lines = watchlist_add_lines(suggestions, holdings=[], watchlist=[])

    assert len(lines) == 8
    assert [ticker for ticker, _ in lines] == [f"T{i}" for i in range(8)]


def test_three_suggestions_are_not_padded_to_the_cap():
    lines = watchlist_add_lines(
        [
            {"ticker": "ARM", "reason": "IPO lockup headlines."},
            {"ticker": "SMCI", "reason": "Supply comment in peer news."},
            {"ticker": "AVGO", "reason": "Custom ASIC order mentioned."},
        ],
        holdings=[],
        watchlist=[],
    )
    note = format_weekly_summary([], lines)

    assert len(lines) == 3
    assert note.count("—") == 3


def test_weekly_note_lists_real_buy_sell_then_watchlist_section():
    note = format_weekly_summary(
        [
            {"ticker": "AAPL", "rating": "BUY", "score": 40},
            {"ticker": "INTC", "rating": "SELL", "score": -55},
            {"ticker": "MSFT", "rating": "HOLD", "score": 2},
            {"ticker": "NVDA", "rating": "STRONG_BUY", "score": 80},
        ],
        [("CRM", "Stored CRM catalyst.")],
    )

    assert note.index("Top buys") < note.index("NVDA")
    assert note.index("NVDA") < note.index("AAPL")
    assert "STRONG_BUY +80" in note
    assert "BUY +40" in note
    assert note.index("Top sells") < note.index("INTC")
    assert "SELL -55" in note
    assert "HOLD" not in note
    assert note.index("Top sells") < note.index("Watchlist adds to consider")
    assert "- CRM — Stored CRM catalyst." in note


def test_suggestions_from_earlier_day_are_stale():
    items = [
        {"ticker": "CRM", "reason": "old", "suggested_at": "2026-07-21T10:00:00+00:00"}
    ]
    assert suggestions_are_stale(items, day="2026-07-22") is True


def test_suggestions_from_today_are_fresh():
    items = [
        {"ticker": "CRM", "reason": "new", "suggested_at": "2026-07-22T02:00:00+00:00"}
    ]
    assert suggestions_are_stale(items, day="2026-07-22") is False
    assert suggestions_are_stale([], day="2026-07-22") is True


def test_stale_refresh_reports_only_what_list_active_returns_after_rebuild():
    suggestions = MagicMock()
    suggestions.list_active.side_effect = [
        [{"ticker": "OLD", "reason": "yesterday", "suggested_at": "2026-07-21T01:00:00+00:00"}],
        [{"ticker": "CRM", "reason": "Model wrote this catalyst.", "suggested_at": "2026-07-22T03:00:00+00:00"}],
    ]
    universe = MagicMock()
    universe.get_universe_detail.return_value = {"holdings": [], "watchlist": []}
    scan = MagicMock()
    scan.rebuild.return_value = {
        "ok": True,
        "ranked": 1,
        "ideas": [{"ticker": "FAKE", "reason": "Do not print this."}],
    }

    note = compose_post_weekly_summary(
        [{"ticker": "AAPL", "rating": "BUY", "score": 10}],
        day="2026-07-22",
        suggestions=suggestions,
        universe=universe,
        idea_scan=scan,
    )

    scan.rebuild.assert_called_once()
    assert "CRM — Model wrote this catalyst." in note
    assert "FAKE" not in note
    assert "Do not print this." not in note
    assert "OLD" not in note


def test_fresh_suggestions_skip_rebuild():
    suggestions = MagicMock()
    suggestions.list_active.return_value = [
        {
            "ticker": "ARM",
            "reason": "Fresh stored reason.",
            "suggested_at": datetime(2026, 7, 22, 1, tzinfo=timezone.utc).isoformat(),
        }
    ]
    universe = MagicMock()
    universe.get_universe_detail.return_value = {
        "holdings": ["ARM"],
        "watchlist": [],
    }
    scan = MagicMock()

    note = compose_post_weekly_summary(
        [],
        day="2026-07-22",
        suggestions=suggestions,
        universe=universe,
        idea_scan=scan,
    )

    scan.rebuild.assert_not_called()
    suggestions.list_active.assert_called_once()
    assert "No model watchlist suggestions this week" in note
    assert "ARM" not in note
    assert "Fresh stored reason." not in note
