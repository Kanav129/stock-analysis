"""Stock quotes and technicals derived from local stock_data."""
from __future__ import annotations

from typing import Any

import pandas as pd

from db.db_factory import get_db_client


def _safe_float(v: Any, default: float | None = None) -> float | None:
    if v is None:
        return default
    try:
        f = float(v)
        if f != f:  # NaN
            return default
        return f
    except (TypeError, ValueError):
        return default


class QuotesService:
    def get_quotes(self, tickers: list[str], spark_days: int = 30) -> dict[str, dict[str, Any]]:
        """Latest price (any bar), prior daily close, and daily sparkline.

        Sparklines read ``1d`` bars only (avoids scanning dense 1m/15m rows).
        Latest price uses a short lookback so the interval index stays selective.
        """
        tickers = [t.upper() for t in tickers if t]
        if not tickers:
            return {}

        db = get_db_client()
        ticker_tuple = tuple(tickers)
        lookback_days = max(int(spark_days) + 5, 40)

        # Sparkline: daily closes only — critical after multi-resolution ladder.
        daily_rows, _ = db.fetch_query(
            """
            SELECT ticker, date AS trade_date, close
            FROM stock_data
            WHERE ticker IN %s
              AND bar_interval = '1d'
              AND close IS NOT NULL
              AND date >= CURRENT_DATE - %s * INTERVAL '1 day'
            ORDER BY ticker, date ASC
            """,
            (ticker_tuple, lookback_days),
        )

        by_ticker: dict[str, list[tuple[Any, float]]] = {t: [] for t in tickers}
        for ticker, trade_date, close in daily_rows:
            by_ticker.setdefault(ticker, []).append((trade_date, float(close)))

        # Latest trade: prefer recent bars (uses ticker/ts index), then fill gaps via 1d.
        latest_rows, _ = db.fetch_query(
            """
            SELECT DISTINCT ON (ticker) ticker, close, bar_ts, bar_interval
            FROM stock_data
            WHERE ticker IN %s
              AND close IS NOT NULL
              AND bar_ts >= NOW() - INTERVAL '7 days'
            ORDER BY ticker, bar_ts DESC
            """,
            (ticker_tuple,),
        )
        latest_map: dict[str, dict[str, Any]] = {
            row[0]: {
                "close": float(row[1]) if row[1] is not None else None,
                "as_of": row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2]),
                "interval": row[3],
            }
            for row in latest_rows
        }
        missing = [t for t in tickers if t not in latest_map]
        if missing:
            fallback_rows, _ = db.fetch_query(
                """
                SELECT DISTINCT ON (ticker) ticker, close, bar_ts, bar_interval
                FROM stock_data
                WHERE ticker IN %s
                  AND bar_interval = '1d'
                  AND close IS NOT NULL
                ORDER BY ticker, bar_ts DESC
                """,
                (tuple(missing),),
            )
            for row in fallback_rows:
                latest_map[row[0]] = {
                    "close": float(row[1]) if row[1] is not None else None,
                    "as_of": row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2]),
                    "interval": row[3],
                }

        result: dict[str, dict[str, Any]] = {}
        for ticker in tickers:
            series = by_ticker.get(ticker) or []
            spark = [c for _, c in series][-spark_days:]
            prior_daily = spark[-2] if len(spark) >= 2 else (spark[-1] if spark else None)
            latest_info = latest_map.get(ticker) or {}
            latest = latest_info.get("close")
            if latest is None and spark:
                latest = spark[-1]
            change_pct = None
            if latest is not None and prior_daily is not None and prior_daily != 0:
                # Intraday change vs prior daily close when possible
                change_pct = round((latest - prior_daily) / prior_daily * 100, 2)
            elif len(spark) >= 2 and spark[-2] != 0:
                change_pct = round((spark[-1] - spark[-2]) / spark[-2] * 100, 2)

            result[ticker] = {
                "ticker": ticker,
                "latest_close": latest,
                "prior_close": prior_daily,
                "change_pct": change_pct,
                "spark": spark,
                "as_of": latest_info.get("as_of")
                or (
                    series[-1][0].isoformat()
                    if series and hasattr(series[-1][0], "isoformat")
                    else (str(series[-1][0]) if series else None)
                ),
                "bar_interval": latest_info.get("interval"),
            }
        return result

    def get_technicals(self, ticker: str) -> dict[str, Any]:
        """Compute RSI, MACD, MAs, 52w range, ATR from daily bars only."""
        ticker = ticker.upper()
        db = get_db_client()
        rows, _ = db.fetch_query(
            """
            SELECT date, open, high, low, close, volume
            FROM stock_data
            WHERE ticker = %s
              AND bar_interval = '1d'
              AND date >= CURRENT_DATE - INTERVAL '400 days'
            ORDER BY date ASC
            """,
            (ticker,),
        )
        if not rows:
            # Fallback: synthesize daily from any bars
            rows, _ = db.fetch_query(
                """
                SELECT DISTINCT ON (date)
                    date, open, high, low, close, volume
                FROM stock_data
                WHERE ticker = %s
                  AND date >= CURRENT_DATE - INTERVAL '400 days'
                ORDER BY date ASC, bar_ts DESC
                """,
                (ticker,),
            )
        if not rows:
            return {"ticker": ticker, "available": False}

        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)

        rsi = self._calc_rsi(close)
        macd = self._calc_macd(close)
        atr = self._calc_atr(high, low, close)

        year = df.tail(252) if len(df) >= 252 else df
        high_52w = _safe_float(year["high"].max())
        low_52w = _safe_float(year["low"].min())
        latest = _safe_float(close.iloc[-1])

        return {
            "ticker": ticker,
            "available": True,
            "latest_close": latest,
            "rsi_14": round(rsi, 2) if rsi is not None else None,
            "macd": {
                "macd_line": round(macd["macd_line"], 4),
                "signal_line": round(macd["signal_line"], 4),
                "histogram": round(macd["histogram"], 4),
            },
            "sma_20": round(self._calc_sma(close, 20), 4) if len(close) >= 20 else None,
            "sma_50": round(self._calc_sma(close, 50), 4) if len(close) >= 50 else None,
            "sma_200": round(self._calc_sma(close, 200), 4) if len(close) >= 200 else None,
            "high_52w": high_52w,
            "low_52w": low_52w,
            "atr_14": atr["atr"],
            "atr_pct": atr["atr_pct"],
            "as_of": df["date"].iloc[-1].isoformat()
            if hasattr(df["date"].iloc[-1], "isoformat")
            else str(df["date"].iloc[-1]),
        }

    @staticmethod
    def _calc_sma(series: pd.Series, window: int) -> float:
        return float(series.rolling(window).mean().iloc[-1])

    @staticmethod
    def _calc_rsi(series: pd.Series, period: int = 14) -> float | None:
        if len(series) < period + 1:
            return None
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.rolling(period).mean().iloc[-1]
        avg_loss = loss.rolling(period).mean().iloc[-1]
        if avg_loss is None or float(avg_loss) == 0:
            return 100.0
        rs = float(avg_gain) / float(avg_loss)
        return float(100.0 - (100.0 / (1.0 + rs)))

    @staticmethod
    def _calc_macd(series: pd.Series) -> dict[str, float]:
        if len(series) < 26:
            return {"macd_line": 0.0, "signal_line": 0.0, "histogram": 0.0}
        ema12 = series.ewm(span=12, adjust=False).mean()
        ema26 = series.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal = macd_line.ewm(span=9, adjust=False).mean()
        histogram = macd_line - signal
        return {
            "macd_line": float(macd_line.iloc[-1]),
            "signal_line": float(signal.iloc[-1]),
            "histogram": float(histogram.iloc[-1]),
        }

    @staticmethod
    def _calc_atr(
        high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
    ) -> dict[str, float | None]:
        if len(close) < period + 1:
            return {"atr": None, "atr_pct": None}
        tr = pd.concat(
            [
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = float(tr.rolling(period).mean().iloc[-1])
        price = float(close.iloc[-1]) if len(close) > 0 else 1.0
        return {
            "atr": round(atr, 4),
            "atr_pct": round(atr / price * 100, 2) if price > 0 else 0.0,
        }
