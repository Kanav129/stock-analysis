from config.report_config import format_market_markdown


def _sample_market_data() -> dict:
    return {
        "live_price": 100.0,
        "volume_latest": 2_000_000,
        "volume_avg_20d": 1_000_000,
        "volume_ratio": 2.0,
        "moving_averages": {
            "ema_10": 98.0,
            "sma_20": 97.0,
            "sma_50": 95.0,
            "sma_200": 90.0,
            "price_vs_ema_10_pct": 2.0,
            "price_vs_sma_20_pct": 3.1,
            "price_vs_sma_50_pct": 5.3,
            "price_vs_sma_200_pct": 11.1,
            "bullish_alignment": True,
        },
        "rsi": 62.0,
        "rsi_regime": "neutral",
        "macd_line": 1.2,
        "macd_signal": 0.8,
        "macd_histogram": 0.4,
        "atr": 2.5,
        "atr_pct": 2.5,
        "wide_range_flag": False,
        "amplitude_pct": 1.8,
        "supports": [{"label": "sma_50", "value": 95.0}],
        "resistances": [{"label": "bollinger_upper", "value": 104.0}],
        "week_52_high": 120.0,
        "week_52_low": 80.0,
        "week_52_from_high_pct": -16.7,
        "week_52_bar_count": 200,
        "price_source": "stock_data",
        "daily_bar_count": 200,
    }


def test_format_market_markdown_includes_price_and_indicators():
    md = format_market_markdown(_sample_market_data())
    assert "## Market / Technicals" in md
    assert "100.00" in md or "100" in md
    assert "RSI" in md
    assert "62" in md
    assert "SMA 50" in md or "sma_50" in md
    assert "MACD" in md
    assert "52-week" in md
    assert "elevated" in md
    assert "stock_data" in md


def test_format_market_markdown_handles_empty():
    md = format_market_markdown({})
    assert "Market / Technicals" in md
    assert "unavailable" in md.lower() or "no price" in md.lower()
