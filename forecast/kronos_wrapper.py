"""Kronos-small time-series forecaster, lazy-loaded on Apple Silicon MPS or CPU."""
from __future__ import annotations

import gc
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from utils.logger import logger

KRONOS_MODEL_ID = "NeoQuasar/Kronos-small"
KRONOS_TOKENIZER_ID = "NeoQuasar/Kronos-Tokenizer-base"
DEFAULT_HISTORY = 200
DEFAULT_HORIZON = 20
MAX_CONTEXT = 512


def _model_dir() -> Path:
    return Path(__file__).resolve().parent / "kronos_model"


def _ensure_kronos_model_code() -> None:
    model_dir = _model_dir()
    if (model_dir / "kronos.py").exists() and (model_dir / "module.py").exists():
        return
    raise RuntimeError(
        "Kronos model code is missing. Run: bash scripts/setup_kronos.sh"
    )


def _prepare_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize yfinance OHLCV to Kronos lowercase schema."""
    out = df.copy()
    rename = {
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    }
    out = out.rename(columns={k: v for k, v in rename.items() if k in out.columns})
    needed = ["open", "high", "low", "close"]
    missing = [c for c in needed if c not in out.columns]
    if missing:
        raise ValueError(f"Missing OHLC columns: {missing}")
    if "volume" not in out.columns:
        out["volume"] = 0.0
    return out[needed + ["volume"]]


class KronosForecaster:
    """Lazy-loads Kronos-small from Hugging Face for price forecasting."""

    def __init__(self) -> None:
        self._predictor: Any = None
        self._device: str = "cpu"

    def _resolve_device(self) -> str:
        try:
            import torch

            if torch.backends.mps.is_available():
                return "mps"
            if torch.cuda.is_available():
                return "cuda:0"
        except ImportError:
            pass
        return "cpu"

    def _load_predictor(self) -> None:
        if self._predictor is not None:
            return

        _ensure_kronos_model_code()
        self._device = self._resolve_device()

        try:
            from forecast.kronos_model import Kronos, KronosPredictor, KronosTokenizer
        except ImportError as exc:
            logger.warning(f"Kronos deps not installed — skipping forecast: {exc}")
            raise RuntimeError(f"Kronos dependencies not installed: {exc}") from exc

        try:
            tokenizer = KronosTokenizer.from_pretrained(KRONOS_TOKENIZER_ID)
            model = Kronos.from_pretrained(KRONOS_MODEL_ID)
            self._predictor = KronosPredictor(
                model,
                tokenizer,
                device=self._device,
                max_context=MAX_CONTEXT,
            )
            logger.info(f"Kronos-small loaded on {self._device}")
        except Exception as exc:
            logger.error(f"Failed to load Kronos model: {exc}")
            raise RuntimeError(f"Kronos-small could not be loaded: {exc}") from exc

    def forecast(self, df: pd.DataFrame, horizon: int = DEFAULT_HORIZON) -> dict[str, Any]:
        """Generate a price forecast for the next `horizon` business days."""
        self._load_predictor()

        history_len = min(len(df), DEFAULT_HISTORY, MAX_CONTEXT)
        hist = _prepare_ohlcv(df.tail(history_len))
        hist = hist[~hist.index.duplicated(keep="last")].sort_index()

        last_actual = float(hist["close"].iloc[-1])
        last_date = pd.Timestamp(hist.index[-1])

        lookback = len(hist)
        x_timestamp = pd.Series(pd.to_datetime(hist.index))
        y_timestamp = pd.Series(
            pd.date_range(
                last_date + timedelta(days=1),
                periods=horizon,
                freq="B",
            )
        )

        try:
            pred_df = self._predictor.predict(
                df=hist,
                x_timestamp=x_timestamp,
                y_timestamp=y_timestamp,
                pred_len=horizon,
                T=1.0,
                top_p=0.9,
                sample_count=1,
                verbose=False,
            )
        except Exception as exc:
            logger.error(f"Kronos inference failed: {exc}")
            return self._drift_fallback(hist, horizon)

        forecast_rows: list[dict[str, Any]] = []
        for i, (date, row) in enumerate(pred_df.iterrows()):
            o = max(float(row["open"]), 0.0)
            c = max(float(row["close"]), 0.0)
            h = max(float(row["high"]), o, c)
            l = min(float(row["low"]), o, c)
            vol = int(max(float(row.get("volume", 0)), 0))
            forecast_rows.append(
                {
                    "day": i + 1,
                    "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
                    "open": round(o, 2),
                    "high": round(h, 2),
                    "low": round(l, 2),
                    "close": round(c, 2),
                    "volume": vol,
                }
            )

        last_close = forecast_rows[-1]["close"]
        delta_pct = (
            round((last_close - last_actual) / last_actual * 100, 2)
            if last_actual > 0
            else 0.0
        )
        direction = "upward" if delta_pct > 0 else "downward"
        all_closes = [r["close"] for r in forecast_rows]
        fcast_range = f"{min(all_closes):.2f}–{max(all_closes):.2f}"
        total_vol = sum(r["volume"] for r in forecast_rows)

        return {
            "model": KRONOS_MODEL_ID,
            "device": self._device,
            "history_days": lookback,
            "horizon": horizon,
            "last_actual": last_actual,
            "last_date": last_date.strftime("%Y-%m-%d"),
            "forecast": forecast_rows,
            "summary": (
                f"Kronos forecasts the close drifting from {last_actual:.2f} (last actual) "
                f"to {last_close:.2f} on day {horizon}, a {delta_pct:+.2f}% move. "
                f"The forecast range spans {fcast_range} and the total forecast volume is {total_vol:,}."
            ),
            "delta_pct": delta_pct,
            "direction": direction,
        }

    def _drift_fallback(self, df: pd.DataFrame, horizon: int) -> dict[str, Any]:
        """Simple drift forecast when Kronos inference fails."""
        close = df["close"] if "close" in df.columns else df["Close"]
        last_actual = float(close.iloc[-1])
        last_date = pd.Timestamp(df.index[-1])

        daily_returns = close.pct_change().dropna()
        mean_return = float(daily_returns.mean())
        std_return = float(daily_returns.std())
        vol_col = "volume" if "volume" in df.columns else "Volume"
        avg_vol = int(df[vol_col].tail(20).mean()) if vol_col in df.columns else 1_000_000
        last_vol = int(df[vol_col].iloc[-1]) if vol_col in df.columns else 1_000_000

        forecast_rows = []
        price = last_actual
        dates = pd.date_range(last_date + timedelta(days=1), periods=horizon, freq="B")
        for i, date in enumerate(dates):
            shock = np.random.normal(mean_return, std_return)
            price = max(price * (1 + shock), 0.01)
            o = price * (1 + np.random.uniform(-0.01, 0.01))
            vol = int(max(last_vol * (1 + np.random.uniform(-0.3, 0.3)), avg_vol * 0.5))
            forecast_rows.append(
                {
                    "day": i + 1,
                    "date": date.strftime("%Y-%m-%d"),
                    "open": round(float(o), 2),
                    "high": round(float(max(o, price * 1.02)), 2),
                    "low": round(float(min(o, price * 0.98)), 2),
                    "close": round(float(price), 2),
                    "volume": vol,
                }
            )

        last_close = forecast_rows[-1]["close"]
        delta_pct = (
            round((last_close - last_actual) / last_actual * 100, 2)
            if last_actual > 0
            else 0.0
        )

        return {
            "model": "drift-fallback (Kronos unavailable)",
            "device": "cpu",
            "history_days": len(df),
            "horizon": horizon,
            "last_actual": last_actual,
            "last_date": last_date.strftime("%Y-%m-%d"),
            "forecast": forecast_rows,
            "summary": (
                f"Drift forecast (Kronos fell back): {last_actual:.2f} → {last_close:.2f} "
                f"({delta_pct:+.2f}%). Daily mean return {mean_return:.4%}, daily vol {std_return:.4%}."
            ),
            "delta_pct": delta_pct,
            "direction": "upward" if delta_pct > 0 else "downward",
        }

    def unload(self) -> None:
        """Release model from memory."""
        if self._predictor is not None:
            del self._predictor
            self._predictor = None
            gc.collect()
            try:
                import torch

                if self._device == "mps":
                    torch.mps.empty_cache()
            except Exception:
                pass
            logger.info("Kronos model unloaded from memory")
