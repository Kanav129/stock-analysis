"""Fundamentals node — local data gathering + 1 LLM call for narrative."""
from __future__ import annotations

from typing import Any, Dict

from langchain_core.prompts import ChatPromptTemplate

from config.llm_config import invoke_research_llm
from config.report_config import annual_revenue_growth_pct
from rag_graphs.research_graph.state import ResearchState
from scraper.alpha_vantage_scraper import AlphaVantageClient
from scraper.yf_cache import get_yf_ticker
from utils.logger import logger

FUNDAMENTALS_SYSTEM = """You are a fundamental equity analyst. Given structured financial data,
write a concise analysis in markdown. Do NOT reproduce the full statement tables.
Include:
1. **Valuation** — 3-5 bullets using the supplied multiples (P/E, PEG, P/B).
2. **Growth & profitability** — revenue trend, margins, FCF in a short paragraph.
3. **Balance sheet** — cash vs debt, leverage, dilution/SBC if relevant.
4. **Bull case** and **Bear case** (3 bullets each).
5. A final **Verdict** paragraph.

Be specific; reference the exact numbers provided. Keep it under 900 words."""


def _first_float(info: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        raw = info.get(key)
        if raw is None or raw == "":
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def _load_info(stock: Any, ticker: str) -> dict[str, Any]:
    """Yahoo quote info. Crumb failures and empty payloads stay empty dicts."""
    try:
        info = stock.info
    except Exception as exc:
        text = str(exc)
        if "crumb" in text.lower():
            logger.error("yfinance info failed for %s: Invalid Crumb (%s)", ticker, text)
        else:
            logger.error("yfinance info failed for %s: %s", ticker, text)
        return {}
    if not isinstance(info, dict):
        logger.error("yfinance info for %s was not a dict", ticker)
        return {}
    return info


def gather_fundamentals(state: ResearchState) -> Dict[str, Any]:
    ticker = state["ticker"]
    logger.info(f"---GATHER FUNDAMENTALS {ticker}---")

    fundamental_data: dict[str, Any] = {}

    # ── yfinance info ──
    try:
        stock = get_yf_ticker(ticker)
    except Exception as exc:
        logger.error("yfinance ticker failed for %s: %s", ticker, exc)
        stock = None
    info = _load_info(stock, ticker) if stock is not None else {}
    if not any(
        _first_float(info, key) is not None
        for key in ("forwardPE", "trailingPE", "beta", "grossMargins", "revenueGrowth")
    ):
        logger.warning(
            "yfinance info for %s has no P/E, beta, or margin fields",
            ticker,
        )

    market_price = state.get("live_price") or (float(info.get("currentPrice", info.get("regularMarketPrice", 0))) or 0.0)
    if not market_price:
        market_price = state.get("live_price", 0.0)

    overview = {
        "market_cap": info.get("marketCap"),
        "forward_pe": info.get("forwardPE"),
        "peg_ratio": info.get("pegRatio") or info.get("PEGRatio"),
        "price_to_book": info.get("priceToBook"),
        "price_to_sales": info.get("priceToSalesTrailing12Months"),
        "eps_ttm": info.get("trailingEps"),
        "forward_eps": info.get("forwardEps"),
        "beta": info.get("beta"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "week_52_high": info.get("fiftyTwoWeekHigh"),
        "week_52_low": info.get("fiftyTwoWeekLow"),
        "employees": info.get("fullTimeEmployees"),
        "description": (info.get("longBusinessSummary") or "")[:500],
        "book_value_per_share": info.get("bookValue"),
    }

    # Clean None values
    overview = {k: (v if v is not None else None) for k, v in overview.items()}

    # ── Alpha Vantage fundamentals ──
    # Read av_fundamentals only. A universe pass must not spend the 25-request
    # daily budget; the drip job (POST /cron/av-backfill) fills the cache.
    try:
        av = AlphaVantageClient()
        av_snapshot = av.get_financial_snapshot(ticker, refresh=False)
        av_errors = av_snapshot.get("errors", {})
        if av_errors:
            logger.warning(f"AV data gaps for {ticker}: {av_errors}")
        # Merge AV overview with yfinance (AV more reliable for some fields)
        av_overview = av_snapshot.get("overview", {})
        if av_overview:
            for key in ("forward_pe", "peg_ratio", "price_to_book", "eps_ttm", "sector", "industry"):
                if av_overview.get(key) and not overview.get(key):
                    overview[key] = av_overview[key]
            if av_overview.get("beta") is not None:
                overview["beta"] = float(av_overview["beta"]) if av_overview["beta"] else overview["beta"]
    except Exception as exc:
        logger.warning(f"Alpha Vantage unavailable for {ticker}: {exc}")
        av_snapshot = {"errors": {"_global": str(exc)}}
        av_errors = {"_global": str(exc)}

    # ── Compute derived metrics ──
    yf_growth = info.get("revenueGrowth")
    avg_revenue_growth = annual_revenue_growth_pct(
        av_snapshot.get("income_annual") if isinstance(av_snapshot, dict) else None,
        yf_revenue_growth=yf_growth,
    )

    # Gross margin from yfinance. Unknown stays None — never a fake 0%.
    gm = _first_float(info, "grossMargins", "grossProfitMargins")
    gross_margin = round(gm * 100, 1) if gm is not None else None

    # FCF margin and cash vs debt only when the inputs were actually returned.
    ocf = _first_float(info, "operatingCashflow")
    capex = _first_float(info, "capitalExpenditure")
    total_cash = _first_float(info, "totalCash")
    total_debt = _first_float(info, "totalDebt")
    revenue = _first_float(info, "totalRevenue")
    fcf_margin = None
    if ocf is not None and capex is not None and revenue is not None and revenue > 0:
        fcf_margin = round((ocf - capex) / revenue * 100, 1)
    cash_exceeds_debt = None
    if total_cash is not None and total_debt is not None:
        cash_exceeds_debt = total_cash > total_debt

    # Shares outstanding trend
    shares_out = info.get("sharesOutstanding")
    implied_shares = info.get("impliedSharesOutstanding")

    # SBC estimate
    sbc = _first_float(info, "stockBasedCompensation")
    sbc_to_rev = None
    if sbc is not None and revenue is not None and revenue > 0:
        sbc_to_rev = round(sbc / revenue * 100, 1)

    fundamental_data = {
        "overview": overview,
        "revenue_growth_pct": avg_revenue_growth,
        "gross_margin_pct": gross_margin,
        "fcf_margin_pct": fcf_margin,
        "cash_exceeds_debt": cash_exceeds_debt,
        "sbc_to_revenue_pct": sbc_to_rev,
        "shares_outstanding": shares_out,
        "market_price": market_price,
        "av_snapshot": av_snapshot,
        "av_errors": av_errors,
    }

    # ── LLM narrative ──
    try:
        prompt = ChatPromptTemplate.from_messages([
            ("system", FUNDAMENTALS_SYSTEM),
            ("human", """Write the fundamentals analysis for {ticker}. Use this structured data:

## Overview
{overview_json}

## Annual Income
{income_annual_json}

## Quarterly Income
{income_quarterly_json}

## Annual Balance Sheet
{balance_annual_json}

## Annual Cash Flow
{cashflow_annual_json}

## Quarterly Cash Flow
{cashflow_quarterly_json}

## Computed Metrics
- Average Revenue Growth: {revenue_growth}%
- Gross Margin: {gross_margin}%
- FCF Margin: {fcf_margin}%
- Cash > Debt: {cash_exceeds_debt}
- SBC / Revenue: {sbc_rev}%
- Market Price: ${market_price}

AV data gaps: {av_errors}

Output the analysis in markdown."""),
        ])
        result, _ = invoke_research_llm(
            prompt,
            {
                "ticker": ticker,
                "overview_json": str(overview),
                "income_annual_json": str(av_snapshot.get("income_annual", [])[:5]),
                "income_quarterly_json": str(av_snapshot.get("income_quarterly", [])[:6]),
                "balance_annual_json": str(av_snapshot.get("balance_annual", [])[:3]),
                "cashflow_annual_json": str(av_snapshot.get("cashflow_annual", [])[:3]),
                "cashflow_quarterly_json": str(av_snapshot.get("cashflow_quarterly", [])[:5]),
                "revenue_growth": str(avg_revenue_growth),
                "gross_margin": str(gross_margin),
                "fcf_margin": str(fcf_margin),
                "cash_exceeds_debt": str(cash_exceeds_debt),
                "sbc_rev": str(sbc_to_rev),
                "market_price": f"{market_price:.2f}" if market_price else "N/A",
                "av_errors": str(av_errors) if av_errors else "None",
            },
            temperature=0.2,
        )
        markdown = result.content if hasattr(result, "content") else str(result)
    except Exception as exc:
        logger.error(f"Fundamentals LLM failed: {exc}")
        markdown = f"*Fundamentals analysis could not be generated: {exc}*"

    return {"fundamental_data": fundamental_data, "sections_markdown": {"fundamentals": markdown}}