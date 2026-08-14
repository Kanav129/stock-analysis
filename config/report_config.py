"""Research report configuration and factor score computation."""
from __future__ import annotations

import os
from typing import Any


# ── Report model (section generation; decision uses ANALYSIS_MODEL separately) ──

REPORT_MODEL = os.getenv("RESEARCH_MODEL", os.getenv("ANALYSIS_MODEL", "qwen3.7-flash"))
REPORT_TEMPERATURE = 0.2

# ── Section definitions ──────────────────────────────────────────

CORE_SECTIONS = [
    {"id": "market", "label": "Market / Technicals", "order": 1},
    {"id": "fundamentals", "label": "Fundamentals", "order": 2},
    {"id": "news", "label": "News / Macro", "order": 3},
    {"id": "sentiment", "label": "Sentiment", "order": 4},
    {"id": "catalysts", "label": "Earnings / Street", "order": 4.5},
]

DEEP_SECTIONS = [
    {"id": "flows", "label": "Hot Money / Flows", "order": 5},
    {"id": "policy", "label": "Policy", "order": 6},
    {"id": "lockup", "label": "Lockup", "order": 7},
    {"id": "kronos", "label": "Kronos Forecast", "order": 8},
]

DEBATE_SECTIONS = [
    {"id": "research_plan", "label": "Research Plan", "order": 9},
    {"id": "trader_plan", "label": "Trader Proposal", "order": 10},
    {"id": "portfolio_decision", "label": "Portfolio Decision", "order": 11},
]

ALL_SECTIONS = CORE_SECTIONS + DEEP_SECTIONS + DEBATE_SECTIONS

FACTOR_INPUT_KEYS = (
    "forward_pe",
    "beta",
    "revenue_growth_pct",
    "gross_margin_pct",
    "fcf_margin_pct",
    "cash_exceeds_debt",
)


def _fmt_num(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def format_market_markdown(market_data: dict[str, Any] | None) -> str:
    """Deterministic Market / Technicals section from structured market_data."""
    data = market_data or {}
    if not data.get("live_price"):
        return (
            "## Market / Technicals\n\n"
            "*Price data unavailable — technicals could not be computed.*\n"
        )

    ma = data.get("moving_averages") or {}
    vol_ratio = data.get("volume_ratio")
    try:
        vr = float(vol_ratio)
        vol_regime = "elevated" if vr >= 1.5 else ("light" if vr < 0.7 else "normal")
    except (TypeError, ValueError):
        vol_regime = "n/a"
    week_52 = ""
    if data.get("week_52_high") or data.get("week_52_low"):
        from_high = data.get("week_52_from_high_pct")
        from_high_txt = (
            f"; live {_fmt_num(from_high, 1)}% vs high"
            if from_high is not None
            else ""
        )
        bars = data.get("week_52_bar_count") or data.get("daily_bar_count") or "—"
        week_52 = (
            f"- **52-week range** ({bars}d lookback): "
            f"${_fmt_num(data.get('week_52_low'))} – "
            f"${_fmt_num(data.get('week_52_high'))}{from_high_txt}"
        )
    lines = [
        "## Market / Technicals",
        "",
        f"- **Live price**: ${_fmt_num(data.get('live_price'))} "
        f"(source: {data.get('price_source', 'unknown')}, "
        f"{data.get('daily_bar_count', '—')} daily bars)",
        f"- **RSI (14)**: {_fmt_num(data.get('rsi'), 1)} "
        f"({data.get('rsi_regime', 'n/a')})",
        f"- **MACD hist**: {_fmt_num(data.get('macd_histogram'))} "
        f"(line {_fmt_num(data.get('macd_line'))} / "
        f"signal {_fmt_num(data.get('macd_signal'))})",
        f"- **ATR**: {_fmt_num(data.get('atr'))} "
        f"({_fmt_num(data.get('atr_pct'), 2)}%)",
        f"- **Volume**: {data.get('volume_latest', '—')} vs 20d avg "
        f"{data.get('volume_avg_20d', '—')} "
        f"(ratio {data.get('volume_ratio', '—')}, {vol_regime})",
    ]
    if week_52:
        lines.append(week_52)
    lines.extend([
        "",
        "| Average | Level | vs price |",
        "|---|---:|---:|",
    ])
    for key, label in (
        ("ema_10", "EMA 10"),
        ("sma_20", "SMA 20"),
        ("sma_50", "SMA 50"),
        ("sma_200", "SMA 200"),
    ):
        level = ma.get(key)
        vs = ma.get(f"price_vs_{key}_pct")
        lines.append(
            f"| {label} | {_fmt_num(level)} | {_fmt_num(vs, 1)}% |"
        )
    alignment = "bullish stack" if ma.get("bullish_alignment") else "mixed / not stacked"
    lines.extend(["", f"- **MA alignment**: {alignment}"])

    supports = data.get("supports") or []
    resistances = data.get("resistances") or []
    if supports:
        bits = [f"{s.get('label')} {_fmt_num(s.get('value'))}" for s in supports]
        lines.append(f"- **Supports**: {', '.join(bits)}")
    if resistances:
        bits = [f"{r.get('label')} {_fmt_num(r.get('value'))}" for r in resistances]
        lines.append(f"- **Resistances**: {', '.join(bits)}")
    lines.append("")
    return "\n".join(lines)


def _fiscal_sort_key(row: dict[str, Any]) -> str:
    return str(
        row.get("fiscalDateEnding")
        or row.get("fiscal_date_ending")
        or row.get("date")
        or ""
    )


def _row_revenue(row: dict[str, Any]) -> float | None:
    raw = row.get("totalRevenue") or row.get("total_revenue") or row.get("revenue")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value else None


def annual_revenue_growth_pct(
    income_annual: list[dict[str, Any]] | None,
    yf_revenue_growth: float | None = None,
) -> float:
    """Average YoY revenue growth. Sorts fiscal periods ascending (oldest first).

    ``yf_revenue_growth`` is yfinance's trailing growth as a fraction (0.18 = 18%).
    """
    rows = [r for r in (income_annual or []) if isinstance(r, dict)]
    rows = sorted(rows, key=_fiscal_sort_key)
    revenues: list[float] = []
    for row in rows:
        rev = _row_revenue(row)
        if rev is not None:
            revenues.append(rev)
    growths: list[float] = []
    for prev, curr in zip(revenues, revenues[1:]):
        if prev:
            growths.append((curr - prev) / prev * 100)
    if growths:
        return round(sum(growths) / len(growths), 1)
    if yf_revenue_growth is not None:
        try:
            frac = float(yf_revenue_growth)
        except (TypeError, ValueError):
            return 0.0
        # yfinance may already be percent (>1.5) or a 0–1 fraction.
        pct = frac * 100 if abs(frac) <= 1.5 else frac
        return round(pct, 1)
    return 0.0


def fundamentals_from_inputs(inputs: dict[str, Any] | None) -> dict[str, Any]:
    """Rebuild the subset of fundamentals needed to recompute factor scores."""
    data = inputs or {}
    return {
        "overview": {
            "forward_pe": data.get("forward_pe"),
            "beta": data.get("beta"),
        },
        "revenue_growth_pct": data.get("revenue_growth_pct", 0),
        "gross_margin_pct": data.get("gross_margin_pct", 0),
        "fcf_margin_pct": data.get("fcf_margin_pct", 0),
        "cash_exceeds_debt": bool(data.get("cash_exceeds_debt", False)),
    }


def _factor_inputs(fundamentals: dict[str, Any]) -> dict[str, Any]:
    overview = fundamentals.get("overview") or {}
    return {
        "forward_pe": overview.get("forward_pe"),
        "beta": overview.get("beta"),
        "revenue_growth_pct": fundamentals.get("revenue_growth_pct", 0),
        "gross_margin_pct": fundamentals.get("gross_margin_pct", 0),
        "fcf_margin_pct": fundamentals.get("fcf_margin_pct", 0),
        "cash_exceeds_debt": bool(fundamentals.get("cash_exceeds_debt", False)),
    }


def compute_factor_scores(
    fundamentals: dict[str, Any],
    market_data: dict[str, Any],
    sentiment_data: dict[str, Any],
) -> dict[str, Any]:
    """Compute standardized 0-100 factor scores deterministically from data.
    These match the sample report's dimensional study outputs."""

    scores: dict[str, Any] = {}

    # ── Value (0–100): lower P/E = higher score ──
    fwd_pe = fundamentals.get("overview", {}).get("forward_pe")
    try:
        fwd_pe_val = float(fwd_pe) if fwd_pe else None
    except (TypeError, ValueError):
        fwd_pe_val = None
    if fwd_pe_val is not None and fwd_pe_val > 0:
        if fwd_pe_val <= 15:
            scores["value"] = 100
        elif fwd_pe_val <= 25:
            scores["value"] = 75
        elif fwd_pe_val <= 40:
            scores["value"] = 50
        elif fwd_pe_val <= 80:
            scores["value"] = 25
        else:
            scores["value"] = 0
    else:
        scores["value"] = 50  # unknown

    # ── Growth (0–100): revenue growth rate ──
    rev_growth = fundamentals.get("revenue_growth_pct", 0)
    try:
        rev_growth_float = float(rev_growth)
    except (TypeError, ValueError):
        rev_growth_float = 0
    if rev_growth_float >= 30:
        scores["growth"] = 100
    elif rev_growth_float >= 20:
        scores["growth"] = 75
    elif rev_growth_float >= 10:
        scores["growth"] = 50
    elif rev_growth_float >= 5:
        scores["growth"] = 25
    else:
        scores["growth"] = 0

    # ── Quality (0–100): gross margin + FCF margin + debt/cash ──
    gross_margin = fundamentals.get("gross_margin_pct", 0)
    fcf_margin = fundamentals.get("fcf_margin_pct", 0)
    cash_debt_ok = fundamentals.get("cash_exceeds_debt", False)
    try:
        gm = float(gross_margin)
        fm = float(fcf_margin)
    except (TypeError, ValueError):
        gm = 0
        fm = 0
    quality = 0
    if gm >= 70:
        quality += 35
    elif gm >= 50:
        quality += 20
    elif gm > 0:
        quality += 10
    if fm > 20:
        quality += 35
    elif fm > 10:
        quality += 20
    elif fm > 0:
        quality += 10
    if cash_debt_ok:
        quality += 30
    scores["quality"] = min(quality, 100)

    # ── Momentum (0–100): price vs MAs + RSI + MACD ──
    mom = 0
    ma_data = market_data.get("moving_averages", {})
    if ma_data:
        above_count = sum(
            1 for k in ("ema_10", "sma_20", "sma_50", "sma_200")
            if ma_data.get(k) is not None and ma_data.get(f"price_vs_{k}_pct", 0) > 0
        )
        mom += above_count * 15  # max 60 from MA alignment

    rsi = market_data.get("rsi", 50)
    try:
        rsi_val = float(rsi)
    except (TypeError, ValueError):
        rsi_val = 50
    if 50 < rsi_val <= 70:
        mom += 20
    elif rsi_val <= 50:
        mom += 5

    macd_hist = market_data.get("macd_histogram", 0)
    try:
        macd_hist_val = float(macd_hist) if macd_hist else 0
    except (TypeError, ValueError):
        macd_hist_val = 0
    if macd_hist_val > 0:
        mom += 20
    scores["momentum"] = min(mom, 100)

    # ── Low Risk (0–100): inverse of beta, volatility ──
    beta = fundamentals.get("overview", {}).get("beta")
    try:
        beta_val = float(beta) if beta else 1.0
    except (TypeError, ValueError):
        beta_val = 1.0
    if beta_val <= 0.8:
        scores["low_risk"] = 90
    elif beta_val <= 1.0:
        scores["low_risk"] = 70
    elif beta_val <= 1.3:
        scores["low_risk"] = 50
    elif beta_val <= 1.7:
        scores["low_risk"] = 30
    else:
        scores["low_risk"] = 10

    # Penalize for high ATR relative to price
    atr_pct = market_data.get("atr_pct", 0)
    try:
        atr_pct_val = float(atr_pct)
    except (TypeError, ValueError):
        atr_pct_val = 0
    if atr_pct_val > 8:
        scores["low_risk"] = max(scores["low_risk"] - 20, 0)
    elif atr_pct_val > 5:
        scores["low_risk"] = max(scores["low_risk"] - 10, 0)

    # ── Sentiment (0–100) — StockTwits only ──
    st = sentiment_data.get("stocktwits", {})
    bullish_pct = st.get("bullish_pct", 0)
    scores["sentiment"] = min(max(int(bullish_pct), 0), 100)
    scores["_inputs"] = _factor_inputs(fundamentals)

    return scores


def compute_dimension_alignment(
    scores: dict[str, int], rating: str
) -> dict[str, Any]:
    """Evaluate how well factor scores align with the rating decision."""
    supporting: list[str] = []
    conflicting: list[str] = []

    thresholds = {
        "STRONG_BUY": 55,
        "BUY": 55,
        "ACCUMULATE": 50,
        "HOLD": 45,
        "REDUCE": 50,
        "SELL": 55,
        "STRONG_SELL": 55,
    }
    threshold = thresholds.get(rating, 50)

    for factor, score in scores.items():
        if factor.startswith("_") or factor == "sentiment":
            continue
        if not isinstance(score, (int, float)):
            continue
        if score >= threshold:
            supporting.append(factor)
        else:
            conflicting.append(factor)

    if len(supporting) > len(conflicting):
        alignment = "strong"
    elif len(supporting) == len(conflicting):
        alignment = "partial"
    else:
        alignment = "weak"

    return {
        "alignment": alignment,
        "supporting": supporting,
        "conflicting": conflicting,
    }