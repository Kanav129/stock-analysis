"""Research report LangGraph — core-4 and deep-dive report generation."""
from __future__ import annotations

from typing import Any, Dict

from langgraph.graph import END, StateGraph

from config.report_config import compute_factor_scores
from rag_graphs.research_graph.nodes.debate import debate
from rag_graphs.research_graph.nodes.gather_catalysts import gather_catalysts
from rag_graphs.research_graph.nodes.gather_flows import gather_flows
from rag_graphs.research_graph.nodes.gather_fundamentals import gather_fundamentals
from rag_graphs.research_graph.nodes.gather_lockup import gather_lockup
from rag_graphs.research_graph.nodes.gather_news import gather_news
from rag_graphs.research_graph.nodes.gather_prices import gather_prices
from rag_graphs.research_graph.nodes.gather_policy import gather_policy
from rag_graphs.research_graph.nodes.gather_sentiment import gather_sentiment
from rag_graphs.research_graph.nodes.persist_report import persist_report
from rag_graphs.research_graph.nodes.run_kronos import run_kronos
from rag_graphs.research_graph.nodes.synthesize_decision import synthesize_decision
from rag_graphs.research_graph.state import ResearchState
from utils.logger import logger

# ── Node names ──
GATHER_PRICES = "gather_prices"
GATHER_FUNDAMENTALS = "gather_fundamentals"
GATHER_NEWS = "gather_news"
GATHER_SENTIMENT = "gather_sentiment"
GATHER_CATALYSTS = "gather_catalysts"
JOIN_CORE = "join_core_gathers"
SYNTHESIZE_DECISION = "synthesize_decision"
GATHER_FLOWS = "gather_flows"
GATHER_POLICY = "gather_policy"
GATHER_LOCKUP = "gather_lockup"
RUN_KRONOS = "run_kronos"
DEBATE = "debate"
PERSIST = "persist"


def join_core_gathers(state: ResearchState) -> Dict[str, Any]:
    """Fan-in after parallel gathers; recompute factors from fresh data."""
    scores = compute_factor_scores(
        state.get("fundamental_data") or {},
        state.get("market_data") or {},
        state.get("sentiment_data") or {},
    )
    return {"factor_scores": scores}


# ── Build graph ──
graph_builder = StateGraph(state_schema=ResearchState)

# Core nodes
graph_builder.add_node(GATHER_PRICES, gather_prices)
graph_builder.add_node(GATHER_FUNDAMENTALS, gather_fundamentals)
graph_builder.add_node(GATHER_NEWS, gather_news)
graph_builder.add_node(GATHER_SENTIMENT, gather_sentiment)
graph_builder.add_node(GATHER_CATALYSTS, gather_catalysts)
graph_builder.add_node(JOIN_CORE, join_core_gathers)
graph_builder.add_node(SYNTHESIZE_DECISION, synthesize_decision)

# Deep-dive nodes
graph_builder.add_node(GATHER_FLOWS, gather_flows)
graph_builder.add_node(GATHER_POLICY, gather_policy)
graph_builder.add_node(GATHER_LOCKUP, gather_lockup)
graph_builder.add_node(RUN_KRONOS, run_kronos)
graph_builder.add_node(DEBATE, debate)

# Shared
graph_builder.add_node(PERSIST, persist_report)


def should_run_deep(state: ResearchState) -> str:
    report_type = state.get("report_type", "core")
    if report_type == "deep":
        return GATHER_FLOWS
    return SYNTHESIZE_DECISION


graph_builder.set_entry_point(GATHER_PRICES)
graph_builder.add_edge(GATHER_PRICES, GATHER_FUNDAMENTALS)
graph_builder.add_edge(GATHER_PRICES, GATHER_NEWS)
graph_builder.add_edge(GATHER_PRICES, GATHER_SENTIMENT)
graph_builder.add_edge(GATHER_PRICES, GATHER_CATALYSTS)
graph_builder.add_edge(GATHER_FUNDAMENTALS, JOIN_CORE)
graph_builder.add_edge(GATHER_NEWS, JOIN_CORE)
graph_builder.add_edge(GATHER_SENTIMENT, JOIN_CORE)
graph_builder.add_edge(GATHER_CATALYSTS, JOIN_CORE)
graph_builder.add_conditional_edges(JOIN_CORE, should_run_deep, {
    GATHER_FLOWS: GATHER_FLOWS,
    SYNTHESIZE_DECISION: SYNTHESIZE_DECISION,
})

# Deep-dive pipeline (only when report_type == "deep")
graph_builder.add_edge(GATHER_FLOWS, GATHER_POLICY)
graph_builder.add_edge(GATHER_POLICY, GATHER_LOCKUP)
graph_builder.add_edge(GATHER_LOCKUP, RUN_KRONOS)
graph_builder.add_edge(RUN_KRONOS, DEBATE)
graph_builder.add_edge(DEBATE, SYNTHESIZE_DECISION)

# Final leg
graph_builder.add_edge(SYNTHESIZE_DECISION, PERSIST)
graph_builder.add_edge(PERSIST, END)

# ── Compile ──
app = graph_builder.compile()


def run_research_graph(ticker: str, report_type: str = "core") -> dict:
    """Convenience entry point called from the API route.

    Args:
        ticker: Stock ticker (e.g. "AAPL")
        report_type: "core" (4 analysts + decision) or "deep" (all 8 + debate)

    Returns:
        Dict with report_id, ticker, report_type, rating, score.
    """
    logger.info(f"Starting {report_type} research graph for {ticker}")
    state: ResearchState = {
        "ticker": ticker.upper(),
        "report_type": report_type,
        "sections_markdown": {},
        "errors": [],
    }
    try:
        result = app.invoke(state)
        logger.info(
            f"Completed {report_type} research for {ticker}: "
            f"rating={result.get('rating')}, score={result.get('score')}"
        )
        return result
    except Exception as exc:
        logger.error(f"Research graph failed for {ticker}: {exc}")
        raise
