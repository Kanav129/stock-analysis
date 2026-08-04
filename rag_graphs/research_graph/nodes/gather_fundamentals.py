"""Fundamentals node — local data gathering + 1 LLM call for narrative."""
from __future__ import annotations

from typing import Any, Dict

import numpy as np
import yfinance as yf
from langchain_core.prompts import ChatPromptTemplate

from config.llm_config import invoke_research_llm
from config.report_config import compute_factor_scores
from rag_graphs.research_graph.state import ResearchState
from scraper.alpha_vantage_scraper import AlphaVantageClient
from utils.logger import logger

FUNDAMENTALS_SYSTEM = """You are a fundamental equity analyst. Given structured financial data,
write a concise, insightful analysis in markdown. Include:
1. A **Company Overview** table (market cap, sector, employees).
2. A **Valuation Snapshot** table (forward P/E, PEG, P/B, EPS, beta, 52w range).
3. **Revenue Growth** trends (annual + quarterly tables).
4. **Profitability** analysis (gross margin, operating margin, net margin trends).
5. **Cash Flow** analysis (OCF, CapEx, FCF trends).
6. **Balance Sheet Health** (cash, debt, current ratio, D/E).
7. A **Risk Factors** table (valuation, SBC, competition, macro).
8. A **Fundamental Summary** table with signals (growth, profitability, cash flow, liquidity, leverage, valuation, efficiency, dilution, volatility).
9. **Bull case** and **Bear case** bullet points.
10. A final **Verdict** paragraph.

Be specific; reference the exact numbers provided. Keep it under 1500 words."""


def gather_fundamentals(state: ResearchState) -> Dict[str, Any]:
    ticker = state["ticker"]
    logger.info(f"---GATHER FUNDAMENTALS {ticker}---")

    fundamental_data: dict[str, Any] = {}

    # ── yfinance info ──
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
    except Exception as exc:
        logger.error(f"yfinance info failed: {exc}")
        info = {}

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
    try:
        av = AlphaVantageClient()
        av_snapshot = av.get_financial_snapshot(ticker)
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
    avg_revenue_growth = 0.0
    try:
        income_annual = av_snapshot.get("income_annual", [])
        revs = []
        for r in income_annual[:5]:
            rev = r.get("totalRevenue")
            if rev:
                revs.append(float(rev))
        growths = []
        for i in range(1, len(revs)):
            if revs[i - 1] and revs[i - 1] != 0:
                growths.append((revs[i] - revs[i - 1]) / revs[i - 1] * 100)
        if growths:
            avg_revenue_growth = round(sum(growths) / len(growths), 1)
    except Exception:
        pass

    # Gross margin from yfinance
    gross_margin = 0.0
    try:
        gm = info.get("grossMargins") or info.get("grossProfitMargins")
        if gm:
            gross_margin = round(float(gm) * 100, 1)
    except (TypeError, ValueError):
        pass

    # FCF margin
    fcf_margin = 0.0
    cash_exceeds_debt = False
    try:
        ocf = info.get("operatingCashflow") or 0.0
        capex = info.get("capitalExpenditure") or 0.0
        total_cash = info.get("totalCash") or 0.0
        total_debt = info.get("totalDebt") or 0.0
        rev = info.get("totalRevenue") or 0.0
        if rev and rev > 0:
            fcf_margin = round((float(ocf) - float(capex)) / float(rev) * 100, 1)
        cash_exceeds_debt = float(total_cash) > float(total_debt)
    except (TypeError, ValueError):
        pass

    # Shares outstanding trend
    shares_out = info.get("sharesOutstanding")
    implied_shares = info.get("impliedSharesOutstanding")

    # SBC estimate
    sbc = info.get("stockBasedCompensation") or 0.0
    sbc_to_rev = 0.0
    try:
        rev = info.get("totalRevenue") or 0.0
        if rev and rev > 0:
            sbc_to_rev = round(float(sbc) / float(rev) * 100, 1)
    except (TypeError, ValueError):
        pass

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

    sections = state.get("sections_markdown", {})
    sections["fundamentals"] = markdown

    return {"fundamental_data": fundamental_data, "sections_markdown": sections}