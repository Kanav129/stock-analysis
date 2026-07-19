"""Kronos-small time-series forecaster, lazy-loaded on Apple Silicon MPS.
8 GB M1 Air safe: model is ~100 MB, loaded only during forecast then released."""
from __future__ import annotations

import gc
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

from utils.logger import logger

KRONOS_MODEL_ID = "NeoQuasar/Kronos-small"
DEFAULT_HISTORY = 200
DEFAULT_HORIZON = 20


class KronosForecaster:
    """Lazy-loads Kronos-small from Hugging Face for price forecasting.
    Designed for 8 GB MacBook Air — model is loaded on demand and explicitly released."""

    def __init__(self) -> None:
        self._model: Any = None
        self._device: str = "cpu"

    def _load_model(self) -> None:
        """Load Kronos-small. Tries MPS first, falls back to CPU."""
        if self._model is not None:
            return

        try:
            import torch
            if torch.backends.mps.is_available():
                self._device = "mps"
            else:
                self._device = "cpu"
        except ImportError:
            self._device = "cpu"
            logger.warning("torch not available — Kronos will run on CPU")

        try:
            from transformers import AutoModelForTimeSeriesForecasting
            self._model = AutoModelForTimeSeriesForecasting.from_pretrained(
                KRONOS_MODEL_ID,
                trust_remote_code=True,
            )
            self._model = self._model.to(self._device)
            self._model.eval()
            logger.info(f"Kronos-small loaded on {self._device}")
        except Exception as exc:
            logger.error(f"Failed to load Kronos model: {exc}")
            raise RuntimeError(f"Kronos-small could not be loaded: {exc}") from exc

    def forecast(self, df: pd.DataFrame, horizon: int = DEFAULT_HORIZON) -> dict[str, Any]:
        """Generate a 20-day price forecast.

        Args:
            df: DataFrame with columns [Open, High, Low, Close, Volume], sorted by date ascending.
            horizon: Number of days to forecast (default 20).

        Returns:
            Dict with forecast table, summary stats, and metadata.
        """
        self._load_model()

        # Take last history days
        history_len = min(len(df), DEFAULT_HISTORY)
        df = df.tail(history_len)

        last_actual = float(df["Close"].iloc[-1])
        last_date = df.index[-1]

        # Build input tensor: [batch=1, seq_len, features=5]
        try:
            import torch
            values = df[["Open", "High", "Low", "Close", "Volume"]].values.astype(np.float32)
            tensor = torch.tensor(values, device=self._device).unsqueeze(0)  # [1, T, 5]

            with torch.inference_mode():
                output = self._model.generate(
                    tensor,
                    forecast_horizon=horizon,
                )

            # output shape: [1, T + horizon, 5] — last `horizon` rows are forecast
            forecast_slice = output[0, -horizon:, :].cpu().numpy()  # [horizon, 5]
        except Exception as exc:
            logger.error(f"Kronos inference failed: {exc}")
            # Fallback: drift forecast
            return self._drift_fallback(df, horizon)

        forecast_rows: list[dict[str, Any]] = []
        forecast_dates = pd.date_range(last_date + timedelta(days=1), periods=horizon, freq="B")

        for i, (date, row) in enumerate(zip(forecast_dates, forecast_slice)):
            # Ensure non-negative and reasonable values
            o, h, l, c, v = float(row[0]), float(row[1]), float(row[2]), float(row[3]), int(max(float(row[4]), 0))
            o = max(o, 0.0)
            c = max(c, 0.0)
            h = max(h, o, c)
            l = min(l, o, c)

            forecast_rows.append({
                "day": i + 1,
                "date": date.strftime("%Y-%m-%d"),
                "open": round(o, 2),
                "high": round(h, 2),
                "low": round(l, 2),
                "close": round(c, 2),
                "volume": v,
            })

        last_close = forecast_rows[-1]["close"]
        delta_pct = round((last_close - last_actual) / last_actual * 100, 2) if last_actual > 0 else 0.0
        direction = "upward" if delta_pct > 0 else "downward"
        all_closes = [r["close"] for r in forecast_rows]
        fcast_range = f"{min(all_closes):.2f}–{max(all_closes):.2f}"
        total_vol = sum(r["volume"] for r in forecast_rows)

        return {
            "model": KRONOS_MODEL_ID,
            "device": self._device,
            "history_days": history_len,
            "horizon": horizon,
            "last_actual": last_actual,
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
        """Simple drift + volatility forecast when Kronos inference fails."""
        close = df["Close"]
        last_actual = float(close.iloc[-1])
        last_date = df.index[-1]

        # Daily returns stats
        daily_returns = close.pct_change().dropna()
        mean_return = float(daily_returns.mean())
        std_return = float(daily_returns.std())
        avg_vol = int(df["Volume"].tail(20).mean()) if "Volume" in df else 1000000
        last_vol = int(df["Volume"].iloc[-1]) if "Volume" in df else 1000000

        forecast_rows = []
        price = last_actual
        dates = pd.date_range(last_date + timedelta(days=1), periods=horizon, freq="B")
        for i, date in enumerate(dates):
            shock = np.random.normal(mean_return, std_return)
            price = price * (1 + shock)
            price = max(price, 0.01)
            o = price * (1 + np.random.uniform(-0.01, 0.01))
            vol = int(max(last_vol * (1 + np.random.uniform(-0.3, 0.3)), avg_vol * 0.5))
            forecast_rows.append({
                "day": i + 1,
                "date": date.strftime("%Y-%m-%d"),
                "open": round(float(o), 2),
                "high": round(float(max(o, price * 1.02)), 2),
                "low": round(float(min(o, price * 0.98)), 2),
                "close": round(float(price), 2),
                "volume": vol,
            })

        last_close = forecast_rows[-1]["close"]
        delta_pct = round((last_close - last_actual) / last_actual * 100, 2) if last_actual > 0 else 0.0

        return {
            "model": "drift-fallback (Kronos unavailable)",
            "device": "cpu",
            "history_days": len(df),
            "horizon": horizon,
            "last_actual": last_actual,
            "forecast": forecast_rows,
            "summary": (
                f"Drift forecast (Kronos fell back): {last_actual:.2f} → {last_close:.2f} "
                f"({delta_pct:+.2f}%). Daily mean return {mean_return:.4%}, daily vol {std_return:.4%}."
            ),
            "delta_pct": delta_pct,
            "direction": "upward" if delta_pct > 0 else "downward",
        }

    def unload(self) -> None:
        """Release model from memory. Call after forecast is complete."""
        if self._model is not None:
            del self._model
            self._model = None
            gc.collect()
            try:
                import torch
                if self._device == "mps":
                    torch.mps.empty_cache()
            except Exception:
                pass
            logger.info("Kronos model unloaded from memory")