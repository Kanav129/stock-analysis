"""Generate printable PDF bytes for a saved research report."""
from __future__ import annotations

import re
from typing import Any

from fpdf import FPDF


_SECTION_TITLES = {
    "market": "Market / Technicals",
    "fundamentals": "Fundamentals",
    "news": "News / Macro",
    "sentiment": "Sentiment",
    "catalysts": "Earnings / Street",
    "flows": "Hot Money / Flows",
    "policy": "Policy",
    "lockup": "Lockup",
    "kronos": "Kronos Forecast",
    "research_plan": "Research Plan",
    "trader_plan": "Trader Proposal",
    "portfolio_decision": "Portfolio Decision",
}


def _plain(text: Any) -> str:
    """Strip markdown-ish markup and keep Latin-1-safe text for core PDF fonts."""
    if text is None:
        return ""
    s = str(text)
    s = re.sub(r"```[\s\S]*?```", " ", s)
    s = re.sub(r"`([^`]*)`", r"\1", s)
    s = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"^#{1,6}\s*", "", s, flags=re.MULTILINE)
    s = re.sub(r"[*_~>#]+", "", s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = s.encode("latin-1", "replace").decode("latin-1").strip()
    # Soft-wrap ultra-long tokens so Helvetica multi_cell cannot stall.
    parts: list[str] = []
    for token in re.split(r"(\s+)", s):
        if len(token) <= 80:
            parts.append(token)
            continue
        for i in range(0, len(token), 80):
            parts.append(token[i : i + 80])
            if i + 80 < len(token):
                parts.append(" ")
    return "".join(parts)


def _fmt_price(value: Any) -> str:
    try:
        if value is None:
            return "-"
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "-"


class _ReportPDF(FPDF):
    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", size=8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, f"Page {self.page_no()}/{{nb}}", align="C")


def build_report_pdf(report: dict[str, Any]) -> bytes:
    """Render a research report dict into PDF bytes."""
    ticker = str(report.get("ticker") or "TICKER").upper()
    report_type = str(report.get("report_type") or "core").lower()
    created = str(report.get("created_at") or "")
    rating_obj = report.get("rating") if isinstance(report.get("rating"), dict) else {}
    rating = str(rating_obj.get("rating") or "-")
    score = rating_obj.get("score")
    score_s = "-" if score is None else str(score)
    model = str(report.get("model") or "-")
    live_price = _fmt_price(report.get("live_price"))

    pdf = _ReportPDF(format="Letter", unit="mm")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_left_margin(16)
    pdf.set_right_margin(16)
    pdf.add_page()

    def write_heading(title: str) -> None:
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(0, 0, 0)
        pdf.multi_cell(0, 7, _plain(title), new_x="LMARGIN", new_y="NEXT")

    def write_body(text: str) -> None:
        pdf.set_font("Helvetica", size=10)
        pdf.set_text_color(40, 40, 40)
        body = _plain(text)
        if body:
            pdf.multi_cell(0, 5, body, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(0, 0, 0)
    pdf.multi_cell(0, 10, _plain(f"{ticker} research report"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=11)
    pdf.set_text_color(60, 60, 60)
    meta = (
        f"Type: {report_type}  |  Rating: {rating}  |  Score: {score_s}  |  "
        f"Price: {live_price}  |  Generated: {created}"
    )
    pdf.multi_cell(0, 6, _plain(meta), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    pdf.set_font("Helvetica", size=10)
    pdf.multi_cell(0, 6, _plain(f"Model: {model}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    levels = report.get("entry_levels") if isinstance(report.get("entry_levels"), dict) else None
    if levels:
        write_heading("Entry levels")
        note = levels.get("position_note") or ""
        line = (
            f"Entry {_fmt_price(levels.get('entry'))}  |  "
            f"Stop {_fmt_price(levels.get('stop'))}  |  "
            f"Target {_fmt_price(levels.get('target'))}"
        )
        if note:
            line += f"  |  {note}"
        write_body(line)

    reasoning = rating_obj.get("reasoning")
    if reasoning:
        write_heading("Thesis & reasoning")
        write_body(str(reasoning))

    drivers = rating_obj.get("key_drivers") or []
    if isinstance(drivers, list) and drivers:
        write_heading("Key drivers")
        write_body("\n".join(f"- {d}" for d in drivers))

    factors = report.get("factor_scores") if isinstance(report.get("factor_scores"), dict) else None
    if factors:
        write_heading("Factor scores")
        parts = [f"{k}: {v}" for k, v in factors.items() if not str(k).startswith("_")]
        if parts:
            write_body("  |  ".join(parts))

    sections = report.get("sections") if isinstance(report.get("sections"), dict) else {}
    for key, body in sections.items():
        if not body or str(key).startswith("_"):
            continue
        title = _SECTION_TITLES.get(str(key), str(key).replace("_", " ").title())
        write_heading(title)
        write_body(str(body))

    out = pdf.output()
    if isinstance(out, (bytes, bytearray)):
        return bytes(out)
    return str(out).encode("latin-1", "replace")
