"""Strip personal portfolio fields from API payloads for guest sessions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

HOLDING_STRIP_KEYS = (
    "quantity",
    "avg_cost",
    "market_value",
    "unrealized_pnl",
    "percent_of_nav",
    "account_id",
    "ibkr_mark_price",
    "ibkr_position_value",
    "ibkr_unrealized_pnl",
    "cost_basis_money",
    "cost_basis_price",
    "source_data",
    "fx_rate_to_base",
    "conid",
)

SUMMARY_STRIP_KEYS = (
    "total_value",
    "total_unrealized_pnl",
    "day_change_pct",
    "day_change_value",
    "overall_change_pct",
)


def _strip_holding(row: Any) -> Any:
    if not isinstance(row, dict):
        return row
    out = dict(row)
    for key in HOLDING_STRIP_KEYS:
        if key in out:
            out[key] = None
    return out


def _strip_summary(summary: dict[str, Any]) -> dict[str, Any]:
    out = dict(summary)
    for key in SUMMARY_STRIP_KEYS:
        if key in out:
            out[key] = None
    return out


def sanitize_guest_holdings_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Null quantity/cost/value/P&L on a holdings list + portfolio summary."""
    out = deepcopy(payload)
    holdings = out.get("holdings")
    if isinstance(holdings, list):
        out["holdings"] = [_strip_holding(h) for h in holdings]
    summary = out.get("summary")
    if isinstance(summary, dict):
        out["summary"] = _strip_summary(summary)
    return out


def sanitize_guest_desk_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(snapshot)
    holdings_block = out.get("holdings")
    if isinstance(holdings_block, dict):
        out["holdings"] = sanitize_guest_holdings_payload(holdings_block)
    return out
