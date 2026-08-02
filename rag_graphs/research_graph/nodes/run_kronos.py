"""Kronos forecast node — local ML model inference (no LLM call)."""
from __future__ import annotations

import os
from typing import Any, Dict

import yfinance as yf

from rag_graphs.research_graph.state import ResearchState
from utils.logger import logger


def is_kronos_enabled() -> bool:
    """Return False when KRONOS_ENABLED is explicitly off (e.g. Render 512 MB).

    Default is on so local / larger hosts keep the forecast. Falsy values:
    0, false, no, off (case-insensitive).
    """
    raw = (os.getenv("KRONOS_ENABLED") or "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


def run_kronos(state: ResearchState) -> Dict[str, Any]:
    ticker = state["ticker"]
    logger.info(f"---RUN KRONOS FORECAST {ticker}---")

    kronos_data: dict[str, Any] = {
        "available": False,
        "forecast": [],
        "summary": "",
        "error": "",
    }
    sections = state.get("sections_markdown", {})

    # Skip before yfinance / torch — avoids OOM on 512 MB hosts (Render free/Starter).
    if not is_kronos_enabled():
        logger.info(f"Kronos disabled (KRONOS_ENABLED=false) — skipping {ticker}")
        kronos_data["error"] = "Kronos disabled (KRONOS_ENABLED=false)"
        kronos_data["summary"] = (
            "Forecast unavailable — Kronos is disabled on this host "
            "(set KRONOS_ENABLED=true where RAM allows)."
        )
        sections["kronos"] = (
            "*Kronos forecast disabled on this host to stay within memory limits "
            "(set `KRONOS_ENABLED=true` on a larger instance to enable).*"
        )
        return {"kronos_data": kronos_data, "sections_markdown": sections}

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
            "last_actual": forecast_result.get("last_actual"),
            "last_date": forecast_result.get("last_date"),
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
        kronos_data["summary"] = "Forecast unavailable — install PyTorch and run scripts/setup_kronos.sh."
        markdown = (
            "*Kronos forecast unavailable — install PyTorch (`pip install torch einops huggingface_hub safetensors`) "
            "and fetch model code (`bash scripts/setup_kronos.sh`).*"
        )
    except RuntimeError as exc:
        msg = str(exc)
        if "KRONOS_ENABLED=false" in msg or "Kronos disabled" in msg:
            logger.info(f"Kronos skipped for {ticker}: {exc}")
            kronos_data["error"] = msg
            kronos_data["summary"] = (
                "Forecast unavailable — Kronos is disabled on this host "
                "(set KRONOS_ENABLED=true where RAM allows)."
            )
            markdown = (
                "*Kronos forecast disabled on this host to stay within memory limits "
                "(set `KRONOS_ENABLED=true` on a larger instance to enable).*"
            )
        elif "dependencies not installed" in msg or "No module named" in msg:
            logger.warning(f"Kronos skipped for {ticker}: {exc}")
            kronos_data["error"] = msg
            kronos_data["summary"] = "Forecast unavailable — install PyTorch and run scripts/setup_kronos.sh."
            markdown = (
                "*Kronos forecast unavailable — install PyTorch and run `bash scripts/setup_kronos.sh`.*"
            )
        elif "model code is missing" in msg.lower():
            logger.warning(f"Kronos skipped for {ticker}: {exc}")
            kronos_data["error"] = msg
            kronos_data["summary"] = "Forecast unavailable — Kronos model code not installed."
            markdown = "*Kronos forecast unavailable — run `bash scripts/setup_kronos.sh`.*"
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

    sections["kronos"] = markdown

    return {"kronos_data": kronos_data, "sections_markdown": sections}