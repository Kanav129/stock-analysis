"""Market / technicals node — local compute only, no LLM call."""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any, Dict

import numpy as np
import pandas as pd
import yfinance as yf

from rag_graphs.research_graph.state import ResearchState
from utils.logger import logger


def _calc_ema(series: pd.Series, span: int) -> float:
    return float(series.ewm(span=span, adjust=False).mean().iloc[-1]) if len(series) >= span else float("nan")


def _calc_sma(series: pd.Series, window: int) -> float:
    return float(series.rolling(window=window).mean().iloc[-1]) if len(series) >= window else float("nan")


def _calc_rsi(series: pd.Series, period: int = 14) -> float:
    if len(series) < period + 1:
        return 50.0
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(period).mean().iloc[-1]
    avg_loss = loss.rolling(period).mean().iloc[-1]
    if avg_loss is None or (hasattr(avg_loss, '__float__') and float(avg_loss) == 0):
        return 100.0
    rs = float(avg_gain) / float(avg_loss)
    return float(100.0 - (100.0 / (1.0 + rs)))


def _calc_macd(series: pd.Series) -> dict[str, float]:
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal
    return {
        "macd_line": float(macd_line.iloc[-1]) if len(macd_line) > 0 else 0.0,
        "signal_line": float(signal.iloc[-1]) if len(signal) > 0 else 0.0,
        "histogram": float(histogram.iloc[-1]) if len(histogram) > 0 else 0.0,
    }


def _calc_bollinger(series: pd.Series, window: int = 20, num_std: int = 2) -> dict[str, float]:
    sma = series.rolling(window).mean()
    std = series.rolling(window).std()
    return {
        "upper": float(sma.iloc[-1] + num_std * std.iloc[-1]) if len(sma) > 0 else 0.0,
        "middle": float(sma.iloc[-1]) if len(sma) > 0 else 0.0,
        "lower": float(sma.iloc[-1] - num_std * std.iloc[-1]) if len(sma) > 0 else 0.0,
    }


def _calc_atr(df: pd.DataFrame, period: int = 14) -> dict[str, float]:
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr = float(tr.rolling(period).mean().iloc[-1]) if len(tr) >= period else 0.0
    price = float(close.iloc[-1]) if len(close) > 0 else 1.0
    return {"atr": atr, "atr_pct": round(atr / price * 100, 2) if price > 0 else 0.0}


def gather_prices(state: ResearchState) -> Dict[str, Any]:
    ticker = state["ticker"]
    logger.info(f"---GATHER PRICES {ticker}---")

    try:
        stock = yf.Ticker(ticker)
        df: pd.DataFrame = stock.history(period="6mo")
        if df.empty:
            return {"errors": state.get("errors", []) + [f"No price data for {ticker}"]}
    except Exception as exc:
        logger.error(f"yfinance price fetch failed for {ticker}: {exc}")
        return {"errors": state.get("errors", []) + [str(exc)]}

    close = df["Close"]
    live_price = float(close.iloc[-1])
    volume = df["Volume"]

    ema_10 = _calc_ema(close, 10)
    sma_20 = _calc_sma(close, 20)
    sma_50 = _calc_sma(close, 50)
    sma_200 = _calc_sma(close, 200)

    rsi = _calc_rsi(close)
    macd = _calc_macd(close)
    boll = _calc_bollinger(close)
    atr_data = _calc_atr(df)

    # Wide-range flag
    latest = df.iloc[-1]
    amplitude = float((latest["High"] - latest["Low"]) / latest["Close"] * 100) if latest["Close"] != 0 else 0.0

    # Volume analysis
    avg_vol_20 = float(volume.rolling(20).mean().iloc[-1]) if len(volume) >= 20 else float(volume.mean())
    latest_vol = float(volume.iloc[-1])
    vol_ratio = round(latest_vol / avg_vol_20, 2) if avg_vol_20 > 0 else 1.0

    # Support / resistance levels
    levels = {
        "ema_10": ema_10,
        "sma_20": sma_20,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "bollinger_upper": boll["upper"],
        "bollinger_lower": boll["lower"],
    }

    supports = sorted(
        [(k, v) for k, v in levels.items() if v < live_price],
        key=lambda x: live_price - x[1],
        reverse=True,
    )[:4]
    resistances = sorted(
        [(k, v) for k, v in levels.items() if v > live_price],
        key=lambda x: x[1] - live_price,
    )[:3]

    market_data: dict[str, Any] = {
        "live_price": live_price,
        "volume_latest": int(latest_vol),
        "volume_avg_20d": int(avg_vol_20),
        "volume_ratio": vol_ratio,
        "moving_averages": {
            "ema_10": ema_10,
            "sma_20": sma_20,
            "sma_50": sma_50,
            "sma_200": sma_200,
            "price_vs_ema_10_pct": round((live_price - ema_10) / ema_10 * 100, 1) if ema_10 else 0,
            "price_vs_sma_20_pct": round((live_price - sma_20) / sma_20 * 100, 1) if sma_20 else 0,
            "price_vs_sma_50_pct": round((live_price - sma_50) / sma_50 * 100, 1) if sma_50 else 0,
            "price_vs_sma_200_pct": round((live_price - sma_200) / sma_200 * 100, 1) if sma_200 else 0,
            "bullish_alignment": ema_10 > sma_50 > sma_200,
        },
        "rsi": round(rsi, 1),
        "rsi_regime": "overbought" if rsi > 70 else ("oversold" if rsi < 30 else "neutral"),
        "macd_line": round(macd["macd_line"], 2),
        "macd_signal": round(macd["signal_line"], 2),
        "macd_histogram": round(macd["histogram"], 2),
        "bollinger_upper": round(boll["upper"], 2),
        "bollinger_middle": round(boll["middle"], 2),
        "bollinger_lower": round(boll["lower"], 2),
        "atr": round(atr_data["atr"], 2),
        "atr_pct": atr_data["atr_pct"],
        "wide_range_flag": amplitude > 8.0,
        "amplitude_pct": round(amplitude, 2),
        "supports": [{"label": s[0], "value": round(s[1], 2)} for s in supports],
        "resistances": [{"label": r[0], "value": round(r[1], 2)} for r in resistances],
        # Price history for chart (last 60 days)
        "price_history": [
            {"date": str(idx.date()), "close": float(row["Close"]), "volume": int(row["Volume"])}
            for idx, row in df.tail(60).iterrows()
        ],
    }

    return {
        "market_data": market_data,
        "live_price": live_price,
    }