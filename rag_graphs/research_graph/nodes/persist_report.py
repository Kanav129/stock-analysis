"""Persist completed report to PostgreSQL."""
from __future__ import annotations

from typing import Any, Dict

from rag_graphs.research_graph.state import ResearchState
from services.report_service import ReportService
from services.ratings_service import RatingsService
from utils.logger import logger


def persist_report(state: ResearchState) -> Dict[str, Any]:
    ticker = state["ticker"]
    report_type = state.get("report_type", "core")
    logger.info(f"---PERSIST {report_type.upper()} REPORT {ticker}---")

    decision_ok = state.get("decision_ok", True)
    error_message = state.get("error_message")
    if decision_ok is False or not state.get("rating"):
        raise RuntimeError(
            error_message or "Decision generation failed — report not saved"
        )

    sections = state.get("sections_markdown", {})
    kronos_data = state.get("kronos_data") or {}
    if kronos_data.get("forecast"):
        sections = dict(sections)
        sections["_kronos_data"] = kronos_data
    rating_dict = {
        "rating": state.get("rating"),
        "score": state.get("score"),
        "reasoning": state.get("reasoning", ""),
        "key_drivers": state.get("key_drivers", []),
        "supporting_headlines": state.get("supporting_headlines", []),
        "posture": state.get("posture", ""),
        "calibration_note": state.get("calibration_note", ""),
        "decision_ok": bool(decision_ok),
        "error": error_message,
    }

    report_id = state.get("report_id") or 0
    try:
        svc = ReportService()
        if report_id:
            # Rescore path: update rating on existing report, keep sections
            svc.update_report_rating(
                report_id=report_id,
                rating=rating_dict,
                entry_levels=state.get("entry_levels"),
                model=state.get("model"),
            )
        else:
            report_id = svc.save_report(
                ticker=ticker,
                report_type=report_type,
                sections=sections,
                rating=rating_dict,
                factor_scores=state.get("factor_scores", {}),
                entry_levels=state.get("entry_levels", {}),
                live_price=state.get("live_price"),
                model=state.get("model"),
            )
        RatingsService().save_rating({
            "ticker": ticker,
            "rating": rating_dict["rating"],
            "score": rating_dict["score"],
            "reasoning": rating_dict["reasoning"],
            "key_drivers": rating_dict["key_drivers"],
            "supporting_headlines": rating_dict["supporting_headlines"],
            "price_summary": {"live_price": state.get("live_price"), "source": "research_report"},
            "model": state.get("model"),
            "report_type": report_type,
            "decision_ok": bool(decision_ok),
            "error_message": error_message,
        })
    except Exception as exc:
        logger.error(f"Failed to persist report for {ticker}: {exc}")
        return {"errors": state.get("errors", []) + [f"Persist failed: {exc}"]}

    logger.info(f"Saved {report_type} report {report_id} for {ticker}")
    return {"report_id": report_id}
