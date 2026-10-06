"""Research report configuration and factor score computation."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any


# ── Report model (section generation; decision uses ANALYSIS_MODEL separately) ──

REPORT_MODEL = os.getenv("RESEARCH_MODEL", os.getenv("ANALYSIS_MODEL", "qwen3.7-plus"))
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


def present_float(value: Any) -> float | None:
    """Parse a real number. ``None`` and blanks stay missing; ``0`` is kept."""
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def annual_revenue_growth_pct(
    income_annual: list[dict[str, Any]] | None,
    yf_revenue_growth: float | None = None,
) -> float | None:
    """Average YoY revenue growth. Sorts fiscal periods ascending (oldest first).

    ``yf_revenue_growth`` is yfinance's trailing growth as a fraction (0.18 = 18%).
    Returns ``None`` when neither statements nor a Yahoo growth figure exist.
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
    if yf_revenue_growth is None:
        return None
    frac = present_float(yf_revenue_growth)
    if frac is None:
        return None
    # yfinance may already be percent (>1.5) or a 0–1 fraction.
    pct = frac * 100 if abs(frac) <= 1.5 else frac
    return round(pct, 1)


def _positive_multiple(value: Any) -> float | None:
    number = present_float(value)
    if number is None or number <= 0:
        return None
    return number


def _metric_reusable(inputs: dict[str, Any], key: str) -> bool:
    """True when a stored growth/margin is a real observation, not a 0% default.

    A stored 0 is reusable only when gross margin shows Yahoo info actually
    arrived (so 0% FCF or 0% growth was measured, not filled in).
    """
    number = present_float(inputs.get(key))
    if number is None:
        return False
    if number != 0:
        return True
    gross = present_float(inputs.get("gross_margin_pct"))
    return gross is not None and gross != 0 and key != "gross_margin_pct"


def _cash_reusable(inputs: dict[str, Any]) -> bool:
    cash = inputs.get("cash_exceeds_debt")
    if cash is True:
        return True
    if cash is not False:
        return False
    gross = present_float(inputs.get("gross_margin_pct"))
    return gross is not None and gross != 0


def inputs_have_real_fundamentals(inputs: dict[str, Any] | None) -> bool:
    """True when stored inputs are not the empty-Yahoo zero default."""
    if not isinstance(inputs, dict):
        return False
    if _positive_multiple(inputs.get("forward_pe")) is not None:
        return True
    if present_float(inputs.get("beta")) is not None:
        return True
    for key in ("revenue_growth_pct", "gross_margin_pct", "fcf_margin_pct"):
        if _metric_reusable(inputs, key):
            return True
    return _cash_reusable(inputs)


def fundamentals_have_real_values(fundamental_data: dict[str, Any] | None) -> bool:
    """True when today's gather returned real multiples, growth, or margins."""
    data = fundamental_data or {}
    overview = data.get("overview") or {}
    flat = {
        "forward_pe": overview.get("forward_pe"),
        "beta": overview.get("beta"),
        "revenue_growth_pct": data.get("revenue_growth_pct"),
        "gross_margin_pct": data.get("gross_margin_pct"),
        "fcf_margin_pct": data.get("fcf_margin_pct"),
        "cash_exceeds_debt": data.get("cash_exceeds_debt"),
    }
    return inputs_have_real_fundamentals(flat)


def fundamentals_from_inputs(inputs: dict[str, Any] | None) -> dict[str, Any]:
    """Rebuild the subset of fundamentals needed to recompute factor scores.

    Missing numbers stay ``None``. They are not coerced to 0%.
    """
    data = inputs or {}
    cash = data.get("cash_exceeds_debt")
    rebuilt: dict[str, Any] = {
        "overview": {
            "forward_pe": present_float(data.get("forward_pe")),
            "beta": present_float(data.get("beta")),
        },
        "revenue_growth_pct": present_float(data.get("revenue_growth_pct")),
        "gross_margin_pct": present_float(data.get("gross_margin_pct")),
        "fcf_margin_pct": present_float(data.get("fcf_margin_pct")),
        "cash_exceeds_debt": cash if isinstance(cash, bool) else None,
    }
    if data.get("as_of"):
        rebuilt["fundamentals_as_of"] = data.get("as_of")
    return rebuilt


def apply_previous_fundamentals(
    current: dict[str, Any] | None,
    previous_inputs: dict[str, Any] | None,
    previous_as_of: str | None = None,
) -> dict[str, Any]:
    """Fill missing scoring inputs from the last snapshot that had real numbers.

    Today's measured values win. A previous report of coerced zeros is ignored.
    When the whole fetch failed, ``fundamentals_as_of`` is that snapshot's date.
    """
    data = dict(current or {})
    overview = dict(data.get("overview") or {})
    prev = previous_inputs if isinstance(previous_inputs, dict) else {}
    if not inputs_have_real_fundamentals(prev):
        data["overview"] = overview
        return data

    today_snapshot = {
        "overview": overview,
        "revenue_growth_pct": data.get("revenue_growth_pct"),
        "gross_margin_pct": data.get("gross_margin_pct"),
        "fcf_margin_pct": data.get("fcf_margin_pct"),
        "cash_exceeds_debt": data.get("cash_exceeds_debt"),
    }
    today_had_real = fundamentals_have_real_values(today_snapshot)
    reused: list[str] = []

    if _positive_multiple(overview.get("forward_pe")) is None and _positive_multiple(prev.get("forward_pe")) is not None:
        overview["forward_pe"] = _positive_multiple(prev.get("forward_pe"))
        reused.append("forward_pe")
    if present_float(overview.get("beta")) is None and present_float(prev.get("beta")) is not None:
        overview["beta"] = present_float(prev.get("beta"))
        reused.append("beta")
    for key in ("revenue_growth_pct", "gross_margin_pct", "fcf_margin_pct"):
        if present_float(data.get(key)) is None and _metric_reusable(prev, key):
            data[key] = present_float(prev.get(key))
            reused.append(key)
    if not isinstance(data.get("cash_exceeds_debt"), bool) and _cash_reusable(prev):
        data["cash_exceeds_debt"] = bool(prev.get("cash_exceeds_debt"))
        reused.append("cash_exceeds_debt")

    data["overview"] = overview
    if not reused:
        return data
    data["fundamentals_reused"] = True
    data["fundamentals_reused_fields"] = reused
    as_of = previous_as_of or prev.get("as_of")
    if today_had_real:
        data["fundamentals_reused_as_of"] = as_of
    else:
        data["fundamentals_as_of"] = as_of
        data["fundamentals_carried_forward"] = True
    return data


def _factor_inputs(
    fundamentals: dict[str, Any],
    *,
    as_of: str | None = None,
    reused_as_of: str | None = None,
    reused_fields: list[str] | None = None,
) -> dict[str, Any]:
    overview = fundamentals.get("overview") or {}
    cash = fundamentals.get("cash_exceeds_debt")
    inputs: dict[str, Any] = {
        "forward_pe": present_float(overview.get("forward_pe")),
        "beta": present_float(overview.get("beta")),
        "revenue_growth_pct": present_float(fundamentals.get("revenue_growth_pct")),
        "gross_margin_pct": present_float(fundamentals.get("gross_margin_pct")),
        "fcf_margin_pct": present_float(fundamentals.get("fcf_margin_pct")),
        "cash_exceeds_debt": cash if isinstance(cash, bool) else None,
    }
    if as_of:
        inputs["as_of"] = as_of
    if reused_as_of:
        inputs["reused_as_of"] = reused_as_of
    if reused_fields:
        inputs["reused_fields"] = list(reused_fields)
    return inputs


def compute_factor_scores(
    fundamentals: dict[str, Any],
    market_data: dict[str, Any],
    sentiment_data: dict[str, Any],
) -> dict[str, Any]:
    """Compute standardized 0-100 factor scores deterministically from data.

    Unknown fundamentals score neutral (50) and are listed in ``data_missing``.
    A measured 0% growth or margin still scores as a real low result.
    """

    scores: dict[str, Any] = {}
    missing: set[str] = set()
    overview = fundamentals.get("overview") or {}

    # ── Value (0–100): lower P/E = higher score ──
    fwd_pe_val = present_float(overview.get("forward_pe"))
    if fwd_pe_val is None:
        scores["value"] = 50
        missing.add("forward_pe")
    elif fwd_pe_val <= 0:
        scores["value"] = 50
    elif fwd_pe_val <= 15:
        scores["value"] = 100
    elif fwd_pe_val <= 25:
        scores["value"] = 75
    elif fwd_pe_val <= 40:
        scores["value"] = 50
    elif fwd_pe_val <= 80:
        scores["value"] = 25
    else:
        scores["value"] = 0

    # ── Growth (0–100): revenue growth rate ──
    rev_growth_float = present_float(fundamentals.get("revenue_growth_pct"))
    if rev_growth_float is None:
        scores["growth"] = 50
        missing.add("revenue_growth_pct")
    elif rev_growth_float >= 30:
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
    # Missing legs contribute their midpoint so a blank fetch is 50, not 0.
    gm = present_float(fundamentals.get("gross_margin_pct"))
    fm = present_float(fundamentals.get("fcf_margin_pct"))
    cash_debt_ok = fundamentals.get("cash_exceeds_debt")
    if not isinstance(cash_debt_ok, bool):
        cash_debt_ok = None
    quality = 0
    if gm is None:
        quality += 18
        missing.add("gross_margin_pct")
    elif gm >= 70:
        quality += 35
    elif gm >= 50:
        quality += 20
    elif gm > 0:
        quality += 10
    if fm is None:
        quality += 17
        missing.add("fcf_margin_pct")
    elif fm > 20:
        quality += 35
    elif fm > 10:
        quality += 20
    elif fm > 0:
        quality += 10
    if cash_debt_ok is None:
        quality += 15
        missing.add("cash_exceeds_debt")
    elif cash_debt_ok:
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
    beta_val = present_float(overview.get("beta"))
    if beta_val is None:
        scores["low_risk"] = 50
        missing.add("beta")
    elif beta_val <= 0.8:
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
    data_missing = [key for key in FACTOR_INPUT_KEYS if key in missing]
    if data_missing:
        scores["data_missing"] = data_missing

    as_of = fundamentals.get("fundamentals_as_of")
    if (
        not fundamentals.get("fundamentals_carried_forward")
        and not as_of
        and fundamentals_have_real_values(fundamentals)
    ):
        as_of = datetime.now(timezone.utc).date().isoformat()
    reused_as_of = fundamentals.get("fundamentals_reused_as_of")
    reused_fields = fundamentals.get("fundamentals_reused_fields")
    scores["_inputs"] = _factor_inputs(
        fundamentals,
        as_of=as_of if isinstance(as_of, str) and as_of else None,
        reused_as_of=reused_as_of if isinstance(reused_as_of, str) and reused_as_of else None,
        reused_fields=reused_fields if isinstance(reused_fields, list) else None,
    )

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