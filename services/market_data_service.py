"""Market data for research — prefer synced ``stock_data``, yfinance fallback."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd
import yfinance as yf

from db.db_factory import get_db_client
from utils.logger import logger

MIN_DAILY_BARS = 20
LOOKBACK_DAYS = 400
MAX_STALE_DAYS = 4
YFINANCE_PERIOD = "6mo"


def _calc_ema(series: pd.Series, span: int) -> float:
    if len(series) < span:
        return float("nan")
    return float(series.ewm(span=span, adjust=False).mean().iloc[-1])


def _calc_sma(series: pd.Series, window: int) -> float:
    if len(series) < window:
        return float("nan")
    return float(series.rolling(window=window).mean().iloc[-1])


def _calc_rsi(series: pd.Series, period: int = 14) -> float:
    if len(series) < period + 1:
        return 50.0
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(period).mean().iloc[-1]
    avg_loss = loss.rolling(period).mean().iloc[-1]
    if avg_loss is None or float(avg_loss) == 0:
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
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr = pd.concat(
        [
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = float(tr.rolling(period).mean().iloc[-1]) if len(tr) >= period else 0.0
    price = float(close.iloc[-1]) if len(close) > 0 else 1.0
    return {"atr": atr, "atr_pct": round(atr / price * 100, 2) if price > 0 else 0.0}


def _normalize_yfinance_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).lower() for c in out.columns]
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index)
    out["date"] = out.index.date
    return out[["open", "high", "low", "close", "volume", "date"]]


def _normalize_db_rows(rows: list[tuple]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close"])
    return df


def _latest_trade_date(df: pd.DataFrame) -> date | None:
    if df.empty:
        return None
    last = df["date"].iloc[-1]
    if isinstance(last, datetime):
        return last.date()
    if hasattr(last, "isoformat"):
        return last  # date
    return None


def _db_frame_is_usable(df: pd.DataFrame) -> tuple[bool, str]:
    if len(df) < MIN_DAILY_BARS:
        return False, f"insufficient bars ({len(df)} < {MIN_DAILY_BARS})"
    latest = _latest_trade_date(df)
    if latest is None:
        return False, "no trade dates"
    age_days = (datetime.now(timezone.utc).date() - latest).days
    if age_days > MAX_STALE_DAYS:
        return False, f"stale ({age_days}d old)"
    return True, "ok"


def load_daily_bars_from_db(ticker: str, lookback_days: int = LOOKBACK_DAYS) -> pd.DataFrame:
    db = get_db_client()
    rows, _ = db.fetch_query(
        """
        SELECT date, open, high, low, close, volume
        FROM stock_data
        WHERE ticker = %s
          AND bar_interval = '1d'
          AND close IS NOT NULL
          AND date >= CURRENT_DATE - %s * INTERVAL '1 day'
        ORDER BY date ASC
        """,
        (ticker.upper(), lookback_days),
    )
    if rows:
        return _normalize_db_rows(rows)

    rows, _ = db.fetch_query(
        """
        SELECT DISTINCT ON (date)
            date, open, high, low, close, volume
        FROM stock_data
        WHERE ticker = %s
          AND date >= CURRENT_DATE - %s * INTERVAL '1 day'
        ORDER BY date ASC, bar_ts DESC
        """,
        (ticker.upper(), lookback_days),
    )
    return _normalize_db_rows(rows) if rows else pd.DataFrame()


def load_daily_bars_from_yfinance(ticker: str, period: str = YFINANCE_PERIOD) -> pd.DataFrame:
    stock = yf.Ticker(ticker)
    df: pd.DataFrame = stock.history(period=period)
    if df.empty:
        return pd.DataFrame()
    return _normalize_yfinance_frame(df)


def build_market_data(df: pd.DataFrame, *, source: str) -> dict[str, Any]:
    close = df["close"]
    live_price = float(close.iloc[-1])
    volume = df["volume"]

    ema_10 = _calc_ema(close, 10)
    sma_20 = _calc_sma(close, 20)
    sma_50 = _calc_sma(close, 50)
    sma_200 = _calc_sma(close, 200)

    rsi = _calc_rsi(close)
    macd = _calc_macd(close)
    boll = _calc_bollinger(close)
    atr_data = _calc_atr(df)

    latest = df.iloc[-1]
    amplitude = (
        float((latest["high"] - latest["low"]) / latest["close"] * 100)
        if latest["close"] != 0
        else 0.0
    )

    avg_vol_20 = (
        float(volume.rolling(20).mean().iloc[-1])
        if len(volume) >= 20
        else float(volume.mean())
    )
    latest_vol = float(volume.iloc[-1])
    vol_ratio = round(latest_vol / avg_vol_20, 2) if avg_vol_20 > 0 else 1.0

    levels = {
        "ema_10": ema_10,
        "sma_20": sma_20,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "bollinger_upper": boll["upper"],
        "bollinger_lower": boll["lower"],
    }

    supports = sorted(
        [(k, v) for k, v in levels.items() if not math.isnan(v) and v < live_price],
        key=lambda x: live_price - x[1],
        reverse=True,
    )[:4]
    resistances = sorted(
        [(k, v) for k, v in levels.items() if not math.isnan(v) and v > live_price],
        key=lambda x: x[1] - live_price,
    )[:3]

    def _pct_vs(level: float) -> float:
        if level is None or math.isnan(level) or level == 0:
            return 0
        return round((live_price - level) / level * 100, 1)

    bullish = (
        not math.isnan(ema_10)
        and not math.isnan(sma_50)
        and not math.isnan(sma_200)
        and ema_10 > sma_50 > sma_200
    )

    tail = df.tail(60)
    return {
        "live_price": live_price,
        "volume_latest": int(latest_vol),
        "volume_avg_20d": int(avg_vol_20),
        "volume_ratio": vol_ratio,
        "moving_averages": {
            "ema_10": ema_10,
            "sma_20": sma_20,
            "sma_50": sma_50,
            "sma_200": sma_200,
            "price_vs_ema_10_pct": _pct_vs(ema_10),
            "price_vs_sma_20_pct": _pct_vs(sma_20),
            "price_vs_sma_50_pct": _pct_vs(sma_50),
            "price_vs_sma_200_pct": _pct_vs(sma_200),
            "bullish_alignment": bullish,
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
        "price_history": [
            {
                "date": str(row["date"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]) if pd.notna(row["volume"]) else 0,
            }
            for _, row in tail.iterrows()
        ],
        "price_source": source,
        "daily_bar_count": len(df),
    }


def get_market_data(ticker: str) -> tuple[dict[str, Any] | None, float | None, str | None]:
    """Return (market_data, live_price, error). Prefers synced daily bars."""
    ticker = ticker.upper()

    try:
        db_df = load_daily_bars_from_db(ticker)
        usable, reason = _db_frame_is_usable(db_df)
        if usable:
            logger.info(f"{ticker}: market data from stock_data ({len(db_df)} daily bars)")
            market_data = build_market_data(db_df, source="stock_data")
            return market_data, market_data["live_price"], None
        if not db_df.empty:
            logger.info(f"{ticker}: stock_data not usable ({reason}), falling back to yfinance")
        else:
            logger.info(f"{ticker}: no stock_data bars, falling back to yfinance")
    except Exception as exc:
        logger.warning(f"{ticker}: stock_data read failed ({exc}), falling back to yfinance")

    try:
        yf_df = load_daily_bars_from_yfinance(ticker)
        if yf_df.empty:
            return None, None, f"No price data for {ticker}"
        logger.info(f"{ticker}: market data from yfinance ({len(yf_df)} daily bars)")
        market_data = build_market_data(yf_df, source="yfinance")
        return market_data, market_data["live_price"], None
    except Exception as exc:
        logger.error(f"yfinance price fetch failed for {ticker}: {exc}")
        return None, None, str(exc)
