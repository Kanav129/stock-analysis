"""Kronos forecast node — local ML model inference (no LLM call)."""
from __future__ import annotations

from typing import Any, Dict

import yfinance as yf

from rag_graphs.research_graph.state import ResearchState
from utils.logger import logger


def run_kronos(state: ResearchState) -> Dict[str, Any]:
    ticker = state["ticker"]
    logger.info(f"---RUN KRONOS FORECAST {ticker}---")

    kronos_data: dict[str, Any] = {
        "available": False,
        "forecast": [],
        "summary": "",
        "error": "",
    }

    # ── Get 200-day OHLCV ──
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="200d")
        if df.empty or len(df) < 50:
            kronos_data["error"] = "Insufficient price history (need 50+ days)"
            kronos_data["summary"] = "Forecast unavailable — insufficient data."
            return {"kronos_data": kronos_data}
    except Exception as exc:
        kronos_data["error"] = str(exc)
        kronos_data["summary"] = f"Forecast unavailable — {exc}"
        return {"kronos_data": kronos_data}

    # ── Try Kronos-small ──
    try:
        from forecast.kronos_wrapper import KronosForecaster
        forecaster = KronosForecaster()
        forecast_result = forecaster.forecast(df, horizon=20)
        forecaster.unload()

        kronos_data = {
            "available": True,
            "model": forecast_result["model"],
            "device": forecast_result["device"],
            "history_days": forecast_result["history_days"],
            "horizon": forecast_result["horizon"],
            "forecast": forecast_result["forecast"],
            "summary": forecast_result["summary"],
            "error": "",
        }

        # Build markdown summary
        last_actual = forecast_result["last_actual"]
        last_forecast = forecast_result["forecast"][-1]["close"] if forecast_result["forecast"] else 0
        delta = ((last_forecast - last_actual) / last_actual * 100) if last_actual > 0 else 0
        direction = "upward" if delta > 0 else "downward"

        markdown = f"""## Kronos forecast — {ticker}

**Model:** {forecast_result['model']} · **Device:** {forecast_result['device']} · **History:** {forecast_result['history_days']}d · **Horizon:** {forecast_result['horizon']}d

Kronos forecasts the close drifting from {last_actual:.2f} (last actual) to {last_forecast:.2f} on day 20, a {delta:+.2f}% move.

| Day | Date | Open | High | Low | Close | Volume |
|-----|------|------|------|-----|-------|--------|
"""
        for f in forecast_result["forecast"]:
            markdown += f"| {f['day']} | {f['date']} | {f['open']:.2f} | {f['high']:.2f} | {f['low']:.2f} | {f['close']:.2f} | {f['volume']:,} |\n"

        markdown += "\n*Single-path forecast from the Kronos foundation model. Not investment advice.*\n"

    except ImportError as exc:
        logger.warning(f"Kronos skipped for {ticker} (deps missing): {exc}")
        kronos_data["error"] = f"Kronos dependencies not installed: {exc}"
        kronos_data["summary"] = "Forecast unavailable — install torch and transformers."
        markdown = "*Kronos forecast unavailable — PyTorch/transformers not installed. Run `pip install torch transformers` to enable.*"
    except RuntimeError as exc:
        msg = str(exc)
        if "dependencies not installed" in msg or "No module named" in msg:
            logger.warning(f"Kronos skipped for {ticker}: {exc}")
            kronos_data["error"] = msg
            kronos_data["summary"] = "Forecast unavailable — install torch and transformers."
            markdown = "*Kronos forecast unavailable — PyTorch/transformers not installed.*"
        else:
            logger.error(f"Kronos failed for {ticker}: {exc}")
            kronos_data["error"] = msg
            kronos_data["summary"] = f"Forecast failed: {exc}"
            markdown = f"*Kronos forecast could not be generated: {exc}*"
    except Exception as exc:
        logger.error(f"Kronos failed for {ticker}: {exc}")
        kronos_data["error"] = str(exc)
        kronos_data["summary"] = f"Forecast failed: {exc}"
        markdown = f"*Kronos forecast could not be generated: {exc}*"

    sections = state.get("sections_markdown", {})
    sections["kronos"] = markdown

    return {"kronos_data": kronos_data, "sections_markdown": sections}