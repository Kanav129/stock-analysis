from rag_graphs.research_graph.nodes.synthesize_decision import build_decision_context


def test_build_decision_context_uses_market_not_fundamentals_fallback():
    ctx = build_decision_context(
        ticker="AAPL",
        live_price=190.0,
        factor_scores={"value": 50, "growth": 60, "quality": 55, "momentum": 40, "low_risk": 50, "sentiment": 45},
        sections={
            "market": "## Market / Technicals\nRSI 62, price above SMA 50.",
            "fundamentals": "## Fundamentals\nCash flow strong. Do not use as technicals.",
            "news": "News md",
            "sentiment": "Sent md",
        },
        portfolio_markdown="## Personal Portfolio\n- none",
    )
    market_block = ctx.split("## Fundamentals")[0]
    assert "RSI 62" in market_block
    assert "Do not use as technicals" not in market_block


def test_build_decision_context_includes_deep_and_catalyst_sections():
    ctx = build_decision_context(
        ticker="NVDA",
        live_price=225.0,
        factor_scores={"value": 50, "growth": 50, "quality": 50, "momentum": 50, "low_risk": 50, "sentiment": 50},
        sections={
            "market": "Market md",
            "fundamentals": "Fund md",
            "news": "News md",
            "sentiment": "Sent md",
            "catalysts": "Next earnings 2026-08-20. Street PT 240.",
            "flows": "Insider net selling.",
            "lockup": "Share count stable.",
            "kronos": "Kronos +3% 20d.",
            "research_plan": "**Recommendation**: HOLD",
            "policy": "No material new regulation.",
        },
        portfolio_markdown="## Personal Portfolio\n- none",
    )
    assert "## Earnings / Street" in ctx or "Next earnings" in ctx
    assert "Insider net selling" in ctx
    assert "Kronos +3%" in ctx
    assert "**Recommendation**: HOLD" in ctx
    assert "Share count stable" in ctx
