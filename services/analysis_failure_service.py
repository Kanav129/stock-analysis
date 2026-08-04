"""Persist hard analysis failures for desk visibility."""
from __future__ import annotations

from services.ratings_service import RatingsService
from services.report_service import ReportService


def record_failed_analysis(
    ticker: str,
    error: str,
    report_type: str = "core",
) -> None:
    """Save rating and report failure rows for an unsuccessful analysis."""
    symbol = ticker.upper()
    message = str(error)
    failed_rating = {
        "ticker": symbol,
        "report_type": report_type,
        "decision_ok": False,
        "rating": None,
        "score": None,
        "reasoning": f"Analysis failed: {message}",
        "key_drivers": [],
        "supporting_headlines": [],
        "price_summary": {},
        "error_message": message,
    }
    RatingsService().save_rating(failed_rating)

    ReportService().save_report(
        symbol,
        report_type,
        sections={},
        rating={
            "decision_ok": False,
            "error": message,
            "error_message": message,
            "rating": None,
            "score": None,
            "reasoning": failed_rating["reasoning"],
            "key_drivers": [],
            "supporting_headlines": [],
        },
    )
