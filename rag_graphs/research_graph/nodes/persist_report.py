"""Persist completed report to PostgreSQL."""
from __future__ import annotations

from typing import Any, Dict

from rag_graphs.research_graph.state import ResearchState
from services.report_service import ReportService
from services.ratings_service import RatingsService
from utils.logger import logger


def _rating_deep_request(state: ResearchState) -> dict[str, Any] | None:
    """Core recommendation stored on rating JSON. Enqueue outcome is filled later."""
    if str(state.get("report_type") or "core").strip().lower() == "deep":
        return None
    raw = state.get("deep_request")
    if not isinstance(raw, dict):
        return None
    enqueued_by = raw.get("enqueued_by")
    if enqueued_by not in ("score", "model", "cap_blocked"):
        enqueued_by = None
    return {
        "recommended": raw.get("recommended") is True,
        "reason": " ".join(str(raw.get("reason") or "").split())[:240],
        "enqueued_by": enqueued_by,
    }


def _prior_deep_request(svc: ReportService, ticker: str, report_id: int) -> dict[str, Any] | None:
    try:
        prior = svc.get_report_by_id(ticker, int(report_id))
    except Exception as exc:
        logger.warning("Could not read prior deep request on report %s: %s", report_id, exc)
        return None
    if not isinstance(prior, dict):
        return None
    rating = prior.get("rating")
    if not isinstance(rating, dict):
        return None
    stored = rating.get("deep_request")
    return stored if isinstance(stored, dict) else None


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
    deep_request = _rating_deep_request(state)
    if deep_request is not None:
        rating_dict["deep_request"] = deep_request

    report_id = state.get("report_id") or 0
    try:
        svc = ReportService()
        if report_id:
            # Rescore rewrites rating JSON. Keep the original deep-request
            # audit so a later rescore cannot drop a model enqueue off the cap.
            prior_request = _prior_deep_request(svc, ticker, report_id)
            if prior_request is not None:
                rating_dict["deep_request"] = prior_request
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
