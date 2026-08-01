"""Build personal portfolio context for research LLM prompts."""
from __future__ import annotations

from typing import Any

from services.holdings_service import HoldingsService


def build_portfolio_context(ticker: str) -> dict[str, Any]:
    ticker = ticker.upper()
    holdings = HoldingsService().get_current_holdings()

    usable: list[dict[str, Any]] = []
    for h in holdings:
        mv = h.get("market_value")
        if mv is None:
            continue
        try:
            market_value = float(mv)
        except (TypeError, ValueError):
            continue
        if market_value <= 0:
            continue
        usable.append({
            "ticker": str(h.get("ticker", "")).upper(),
            "quantity": float(h.get("quantity") or 0),
            "market_value": market_value,
            "avg_cost": h.get("avg_cost"),
            "unrealized_pnl": h.get("unrealized_pnl"),
        })

    total_value = sum(p["market_value"] for p in usable)
    positions: list[dict[str, Any]] = []
    for p in sorted(usable, key=lambda x: x["market_value"], reverse=True):
        weight = (p["market_value"] / total_value * 100.0) if total_value else 0.0
        positions.append({
            **p,
            "weight_pct": round(weight, 2),
        })

    current_row = next((p for p in positions if p["ticker"] == ticker), None)
    current = {
        "ticker": ticker,
        "held": current_row is not None,
        "quantity": current_row["quantity"] if current_row else 0.0,
        "market_value": current_row["market_value"] if current_row else 0.0,
        "weight_pct": current_row["weight_pct"] if current_row else 0.0,
        "avg_cost": current_row["avg_cost"] if current_row else None,
    }

    markdown = _render_markdown(
        ticker=ticker,
        has_holdings=bool(positions),
        total_value=total_value,
        position_count=len(positions),
        positions=positions,
        current=current,
    )
    return {
        "has_holdings": bool(positions),
        "total_value": total_value,
        "position_count": len(positions),
        "positions": positions,
        "current": current,
        "markdown": markdown,
    }


def portfolio_markdown_for(ticker: str) -> str:
    return build_portfolio_context(ticker)["markdown"]


def _render_markdown(
    *,
    ticker: str,
    has_holdings: bool,
    total_value: float,
    position_count: int,
    positions: list[dict[str, Any]],
    current: dict[str, Any],
) -> str:
    lines = ["## Personal Portfolio"]
    if not has_holdings:
        lines.append("- No holdings on file for this desk.")
        lines.append(f"- Analyzing {ticker}: not held (watchlist / research only).")
        lines.append(
            "- Use generic position sizing. Do not invent ownership. "
            "Do not nudge rating/score for portfolio concentration."
        )
        return "\n".join(lines)

    lines.append(
        f"- Total value: ${total_value:,.2f} · {position_count} position(s)"
    )
    if current["held"]:
        avg = current.get("avg_cost")
        avg_s = f"${float(avg):.2f}" if avg is not None else "n/a"
        lines.append(
            f"- Analyzing {ticker}: **held** · weight {current['weight_pct']:.2f}% · "
            f"qty {current['quantity']:g} · avg cost {avg_s}"
        )
    else:
        lines.append(f"- Analyzing {ticker}: **not held**")

    lines.append("")
    lines.append("| Ticker | Qty | Market value | Weight % | Unrealized P&L |")
    lines.append("|--------|-----|--------------|----------|----------------|")
    for p in positions:
        pnl = p.get("unrealized_pnl")
        pnl_s = f"${float(pnl):,.2f}" if pnl is not None else "n/a"
        lines.append(
            f"| {p['ticker']} | {p['quantity']:g} | ${p['market_value']:,.2f} | "
            f"{p['weight_pct']:.2f}% | {pnl_s} |"
        )
    lines.append("")
    lines.append(
        "Use this book for position sizing and concentration (infer sectors/industries "
        "from tickers). Prefer stock research for core conviction. Only nudge rating/score "
        "slightly when concentration or size has a clear, material effect; explain any "
        "nudge in reasoning. Reflect ownership in position_note / posture."
    )
    return "\n".join(lines)
