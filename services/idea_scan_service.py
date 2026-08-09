"""Build watchlist suggestions from peer news mentions + market headlines."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from config.llm_config import call_with_retry_then_fallback
from db.mongo_db import MongoDBClient
from scraper.finnhub_scraper import FinnhubClient
from services.portfolio_context_service import portfolio_markdown_for
from services.suggestion_service import SuggestionService
from services.universe_service import UniverseService
from utils.logger import logger

MAX_RANKED = 8
PEER_ARTICLE_LIMIT = 80
MARKET_ARTICLE_LIMIT = 40
HEADLINES_PER_CANDIDATE = 4
ARTICLES_PER_CANDIDATE = 5
MAX_CANDIDATES_FOR_LLM = 40

# Index / mega ETFs and common false-positive tokens from headlines.
NOISE_TICKERS = frozenset(
    {
        "SPY", "QQQ", "IWM", "DIA", "VOO", "VTI", "VT", "IVV", "ARKK",
        "XLF", "XLK", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE",
        "HYG", "LQD", "TLT", "IEF", "GLD", "SLV", "USO", "UNG", "VIX", "UVXY",
        "TQQQ", "SQQQ", "SPXU", "SPXL", "USD", "CEO", "CFO", "IPO", "ETF",
        "GDP", "CPI", "FED", "SEC", "FDA", "AI", "US", "USA", "UK", "EU",
        "NYSE", "NASDAQ", "AMEX", "OTC", "THE", "AND", "FOR", "FROM", "WITH",
        "THIS", "THAT", "WILL", "HAVE", "HAS", "ARE", "WAS", "WERE", "BEEN",
        "INTO", "OVER", "UNDER", "AFTER", "BEFORE", "ABOUT", "THAN", "THEN",
        "WHEN", "WHAT", "WHO", "HOW", "WHY", "ALL", "ANY", "NEW", "NOW", "OUT",
        "TOP", "LOW", "HIGH", "BUY", "SELL", "HOLD", "YEAR", "WEEK", "MONTH",
        "DAY", "Q1", "Q2", "Q3", "Q4", "FY", "EPS", "PE",
    }
)

_TICKER_RE = re.compile(
    r"(?:\$([A-Z]{1,5})\b|(?<![A-Za-z0-9])([A-Z]{2,5})(?![A-Za-z0-9]))"
)


class RankedSuggestion(BaseModel):
    ticker: str = Field(description="US equity ticker symbol")
    reason: str = Field(
        description=(
            "Why this ticker appears on today's suggestion list "
            "(catalyst + optional portfolio note; 80-140 chars)"
        )
    )
    source: str = Field(
        default="both",
        description="peer, market, or both",
    )


class RankedSuggestionList(BaseModel):
    suggestions: list[RankedSuggestion] = Field(
        description=(
            "Zero to eight strong watchlist ideas only. Empty list is valid "
            "when nothing clears the conviction bar."
        )
    )


class BriefReason(BaseModel):
    title: str = Field(description="Short reason title")
    detail: str = Field(description="1-3 sentence explanation")


class BriefSource(BaseModel):
    title: str = Field(description="Headline or source title")
    url: str = Field(description="Exact URL from the provided article list, or empty")
    publisher: str = Field(default="", description="Publisher if known")


class PortfolioFit(BaseModel):
    stance: str = Field(
        description="One of: diversifies, neutral, concentrated"
    )
    warning: str | None = Field(
        default=None,
        description="Concentration warning if stance is concentrated; else null",
    )
    note: str = Field(description="How this fits the user's book")


class SuggestionBriefOutput(BaseModel):
    company_name: str = Field(description="Company display name")
    company_blurb: str = Field(
        description="1-2 sentence company introduction for a desk tile"
    )
    sector: str = Field(default="", description="Sector")
    industry: str = Field(default="", description="Industry")
    thesis: str = Field(description="Short markdown thesis for watching this name")
    reasons: list[BriefReason] = Field(description="3-5 concrete reasons")
    sources: list[BriefSource] = Field(
        description="Sources drawn only from provided article URLs"
    )
    portfolio_fit: PortfolioFit


RANK_SYSTEM = """You are an idea scout for a personal trading desk.
Given candidate tickers from news (peer co-mentions near the user's book, plus
general market headlines) AND the user's personal holdings, pick ONLY names you
strongly believe deserve a watchlist add for further research.

Rules:
- Quality over quantity. Return 0 suggestions if nothing is convincingly good.
- At most 8. Prefer 0–4 strong ideas over padding the list.
- Prefer liquid US equities with a clear near-term catalyst in the headlines.
- Use the holdings table: prefer industries/sectors the book lacks; if the book
  is already heavy in that industry, only recommend if the idea is strong enough
  to justify more concentration — and mention that warning briefly in `reason`.
- Do NOT recommend tickers in the excluded universe.
- Skip mega-index ETFs, macro acronyms, and vague/noisy symbols.
- `reason` must explain WHY the stock appears on today's suggestion list
  (the catalyst / news angle), ~80–140 characters. Not a generic company blurb.
- `source` must be one of: peer, market, both.
"""

BRIEF_SYSTEM = """You write portfolio-aware watchlist pitch briefs for a personal desk.
You receive company profile data, recent headlines/URLs, and the user's holdings.

Produce a convincing brief to help the user decide whether to add the ticker
to their watchlist (not a full BUY/SELL desk rating).

Rules:
- company_blurb: 1–2 sentences introducing what the company does.
- thesis: short markdown (a few paragraphs max) on why watching now makes sense.
- reasons: 3–5 concrete reasons with titles + detail.
- sources: ONLY use URLs from the provided article list. Never invent URLs.
  If an article has no URL, set url to "" and still cite the headline.
- portfolio_fit.stance: diversifies | neutral | concentrated
  - diversifies if this adds exposure the book lacks
  - concentrated if the book is already heavy in this sector/industry
  - neutral otherwise
- If concentrated but still worth watching, set warning to a clear caution and
  still make a strong case in thesis/reasons.
- Be specific; no generic filler.
"""


def extract_tickers(text: str) -> set[str]:
    found: set[str] = set()
    if not text:
        return found
    for match in _TICKER_RE.finditer(text.upper()):
        sym = match.group(1) or match.group(2)
        if not sym or sym in NOISE_TICKERS:
            continue
        if len(sym) < 2:
            continue
        found.add(sym)
    return found


def _is_http_url(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False


def _empty_bucket() -> dict[str, Any]:
    return {
        "mentions": 0,
        "headlines": [],
        "articles": [],
        "sources": set(),
    }


def _add_article(
    bucket: dict[str, Any],
    *,
    headline: str,
    url: str,
    publisher: str,
) -> None:
    if headline and headline not in bucket["headlines"]:
        if len(bucket["headlines"]) < HEADLINES_PER_CANDIDATE:
            bucket["headlines"].append(headline)
    if len(bucket["articles"]) >= ARTICLES_PER_CANDIDATE:
        return
    key = (headline, url)
    existing = {(a.get("title"), a.get("url")) for a in bucket["articles"]}
    if key in existing:
        return
    if headline or url:
        bucket["articles"].append(
            {
                "title": headline,
                "url": url if _is_http_url(url) else "",
                "publisher": publisher or "",
            }
        )


class IdeaScanService:
    def __init__(self) -> None:
        self.universe = UniverseService()
        self.suggestions = SuggestionService()
        self.finnhub = FinnhubClient()
        self.mongo = MongoDBClient()

    def rebuild(self) -> dict[str, Any]:
        """Scan news, rank candidates, eager-brief, upsert. Best-effort."""
        try:
            universe = {t.upper() for t in self.universe.get_tickers()}
            portfolio_md = portfolio_markdown_for("IDEA")
            peer = self._peer_candidates(universe)
            market = self._market_candidates()
            merged = self._merge_candidates(peer, market, universe)
            if not merged:
                self.suggestions.purge_expired()
                logger.info("Idea scan: no candidates outside universe")
                return {"ok": True, "candidates": 0, "ranked": 0, "upserted": 0}

            validated = self._validate_candidates(merged)
            if not validated:
                self.suggestions.purge_expired()
                logger.info("Idea scan: no validated candidates")
                return {"ok": True, "candidates": 0, "ranked": 0, "upserted": 0}

            ranked = self._rank_with_llm(validated, universe, portfolio_md)
            by_ticker = {c["ticker"]: c for c in validated}
            enriched: list[dict[str, Any]] = []
            for item in ranked:
                cand = by_ticker.get(item["ticker"])
                if not cand:
                    continue
                brief_row = self._build_brief(item, cand, portfolio_md)
                if brief_row:
                    enriched.append(brief_row)

            upserted = self.suggestions.upsert_ranked(enriched)
            self.suggestions.purge_expired()
            return {
                "ok": True,
                "candidates": len(validated),
                "ranked": len(ranked),
                "upserted": upserted,
            }
        except Exception as exc:
            logger.error("Idea scan rebuild failed: %s", exc)
            return {"ok": False, "error": str(exc)[:300]}

    def _peer_candidates(self, universe: set[str]) -> dict[str, dict[str, Any]]:
        collection = self.mongo.get_collection()
        since = datetime.now(timezone.utc) - timedelta(days=3)
        cursor = (
            collection.find(
                {"posted": {"$gte": since.isoformat()}},
                {
                    "_id": 0,
                    "ticker": 1,
                    "headline": 1,
                    "description": 1,
                    "link": 1,
                    "source": 1,
                },
            )
            .sort("posted", -1)
            .limit(PEER_ARTICLE_LIMIT)
        )
        out: dict[str, dict[str, Any]] = {}
        for doc in cursor:
            host = str(doc.get("ticker") or "").upper()
            text = f"{doc.get('headline') or ''} {doc.get('description') or ''}"
            headline = str(doc.get("headline") or "").strip()
            url = str(doc.get("link") or "").strip()
            publisher = str(doc.get("source") or "").strip()
            for sym in extract_tickers(text):
                if sym == host or sym in universe:
                    continue
                bucket = out.setdefault(sym, _empty_bucket())
                bucket["mentions"] += 1
                bucket["sources"].add("peer")
                _add_article(
                    bucket, headline=headline, url=url, publisher=publisher
                )
        return out

    def _market_candidates(self) -> dict[str, dict[str, Any]]:
        articles = self.finnhub.get_general_news("general")[:MARKET_ARTICLE_LIMIT]
        out: dict[str, dict[str, Any]] = {}
        for a in articles:
            text = f"{a.get('headline') or ''} {a.get('summary') or ''}"
            related = str(a.get("related") or "")
            if related:
                text = f"{text} {related.replace(',', ' ')}"
            headline = str(a.get("headline") or "").strip()
            url = str(a.get("url") or "").strip()
            publisher = str(a.get("source") or "").strip()
            for sym in extract_tickers(text):
                bucket = out.setdefault(sym, _empty_bucket())
                bucket["mentions"] += 1
                bucket["sources"].add("market")
                _add_article(
                    bucket, headline=headline, url=url, publisher=publisher
                )
        return out

    @staticmethod
    def _merge_candidates(
        peer: dict[str, dict[str, Any]],
        market: dict[str, dict[str, Any]],
        universe: set[str],
    ) -> dict[str, dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for source_map in (peer, market):
            for sym, data in source_map.items():
                if sym in universe or sym in NOISE_TICKERS:
                    continue
                bucket = merged.setdefault(sym, _empty_bucket())
                bucket["mentions"] += int(data.get("mentions") or 0)
                bucket["sources"] |= set(data.get("sources") or [])
                for h in data.get("headlines") or []:
                    if h not in bucket["headlines"] and len(bucket["headlines"]) < HEADLINES_PER_CANDIDATE:
                        bucket["headlines"].append(h)
                for art in data.get("articles") or []:
                    _add_article(
                        bucket,
                        headline=str(art.get("title") or ""),
                        url=str(art.get("url") or ""),
                        publisher=str(art.get("publisher") or ""),
                    )
        return merged

    def _validate_candidates(
        self, candidates: dict[str, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        ranked_syms = sorted(
            candidates.keys(),
            key=lambda s: (-candidates[s]["mentions"], s),
        )[:MAX_CANDIDATES_FOR_LLM]
        validated: list[dict[str, Any]] = []
        for sym in ranked_syms:
            profile = self.finnhub.get_company_profile(sym)
            if not isinstance(profile, dict) or not profile.get("ticker"):
                continue
            fin_type = str(profile.get("type") or "").lower()
            if fin_type and fin_type not in ("", "common stock", "eqs"):
                if "etf" in fin_type or "fund" in fin_type:
                    continue
            data = candidates[sym]
            sources = data["sources"]
            if sources == {"peer"}:
                source = "peer"
            elif sources == {"market"}:
                source = "market"
            else:
                source = "both"
            validated.append(
                {
                    "ticker": sym,
                    "mentions": data["mentions"],
                    "headlines": data["headlines"],
                    "articles": data.get("articles") or [],
                    "source": source,
                    "name": profile.get("name") or "",
                    "sector": profile.get("finnhubIndustry")
                    or profile.get("industry")
                    or "",
                    "industry": profile.get("finnhubIndustry") or "",
                    "profile": profile,
                }
            )
        return validated

    def _rank_with_llm(
        self,
        candidates: list[dict[str, Any]],
        universe: set[str],
        portfolio_md: str,
    ) -> list[dict[str, Any]]:
        lines = []
        for c in candidates:
            heads = "; ".join(c.get("headlines") or []) or "(no headline)"
            sector = c.get("sector") or c.get("industry") or "?"
            lines.append(
                f"- {c['ticker']} ({c.get('name') or '?'}; sector={sector}) "
                f"mentions={c['mentions']} source={c['source']}: {heads}"
            )
        excluded = ", ".join(sorted(universe)[:80]) or "(none)"
        human = (
            f"{portfolio_md}\n\n"
            f"Excluded universe (do not suggest): {excluded}\n\n"
            f"Candidates:\n" + "\n".join(lines)
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", RANK_SYSTEM),
                (
                    "human",
                    "Select strong watchlist suggestions only (0–8):\n\n{context}",
                ),
            ]
        )

        def _invoke(llm):
            structured = llm.with_structured_output(
                RankedSuggestionList,
                method="function_calling",
                include_raw=True,
            )
            return (prompt | structured).invoke({"context": human})

        try:
            result, _model = call_with_retry_then_fallback(
                role="analysis",
                temperature=0.2,
                call=_invoke,
            )
        except Exception as exc:
            logger.error("Idea scan LLM rank failed: %s", exc)
            # Conservative fallback: at most 2 highest-mention names
            return [
                {
                    "ticker": c["ticker"],
                    "reason": (
                        (c["headlines"][0][:137] + "…")
                        if c.get("headlines")
                        else f"Mentioned {c['mentions']}x in recent news"
                    ),
                    "source": c["source"],
                }
                for c in candidates[:2]
            ]

        if isinstance(result, dict) and "parsed" in result:
            result = result["parsed"]
        if result is None:
            return []

        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        by_ticker = {c["ticker"]: c for c in candidates}
        for item in result.suggestions[:MAX_RANKED]:
            ticker = str(item.ticker or "").upper().strip()
            if not ticker or ticker in seen or ticker in universe or ticker in NOISE_TICKERS:
                continue
            if ticker not in by_ticker:
                continue
            reason = str(item.reason or "").strip()
            if not reason:
                continue
            source = str(item.source or by_ticker[ticker]["source"]).strip().lower()
            if source not in ("peer", "market", "both"):
                source = by_ticker[ticker]["source"]
            seen.add(ticker)
            out.append({"ticker": ticker, "reason": reason[:200], "source": source})
        return out

    def _build_brief(
        self,
        ranked: dict[str, Any],
        candidate: dict[str, Any],
        portfolio_md: str,
    ) -> dict[str, Any] | None:
        ticker = ranked["ticker"]
        profile = candidate.get("profile") or {}
        articles = candidate.get("articles") or []
        allowed_urls = {
            str(a.get("url")).strip()
            for a in articles
            if _is_http_url(str(a.get("url") or ""))
        }
        article_lines = []
        for a in articles:
            article_lines.append(
                f"- title={a.get('title')!r} url={a.get('url')!r} "
                f"publisher={a.get('publisher')!r}"
            )
        if not article_lines:
            for h in candidate.get("headlines") or []:
                article_lines.append(f"- title={h!r} url='' publisher=''")

        context = (
            f"Ticker: {ticker}\n"
            f"Profile name: {profile.get('name') or candidate.get('name')}\n"
            f"Finnhub industry: {profile.get('finnhubIndustry') or ''}\n"
            f"Country: {profile.get('country') or ''}\n"
            f"Market cap: {profile.get('marketCapitalization') or ''}\n"
            f"Web: {profile.get('weburl') or ''}\n"
            f"Suggestion reason (why on list): {ranked.get('reason')}\n"
            f"Mention source pool: {ranked.get('source')}\n\n"
            f"Articles (use only these URLs):\n"
            + ("\n".join(article_lines) if article_lines else "(none)")
            + f"\n\n{portfolio_md}"
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", BRIEF_SYSTEM),
                (
                    "human",
                    "Write the watchlist suggestion brief for {ticker}:\n\n{context}",
                ),
            ]
        )

        def _invoke(llm):
            structured = llm.with_structured_output(
                SuggestionBriefOutput,
                method="function_calling",
                include_raw=True,
            )
            return (prompt | structured).invoke(
                {"ticker": ticker, "context": context}
            )

        try:
            result, _model = call_with_retry_then_fallback(
                role="analysis",
                temperature=0.25,
                call=_invoke,
            )
        except Exception as exc:
            logger.error("Idea scan brief failed for %s: %s", ticker, exc)
            return None

        if isinstance(result, dict) and "parsed" in result:
            result = result["parsed"]
        if result is None:
            return None

        sources: list[dict[str, str]] = []
        for s in result.sources or []:
            url = str(s.url or "").strip()
            if url and url not in allowed_urls:
                url = ""
            title = str(s.title or "").strip()
            if not title and not url:
                continue
            sources.append(
                {
                    "title": title or "Source",
                    "url": url,
                    "publisher": str(s.publisher or "").strip(),
                }
            )
        # Ensure we keep real articles even if model skipped them
        if not sources:
            for a in articles:
                if a.get("title") or a.get("url"):
                    sources.append(
                        {
                            "title": str(a.get("title") or "Source"),
                            "url": str(a.get("url") or "")
                            if _is_http_url(str(a.get("url") or ""))
                            else "",
                            "publisher": str(a.get("publisher") or ""),
                        }
                    )

        reasons = [
            {
                "title": str(r.title or "").strip() or "Reason",
                "detail": str(r.detail or "").strip(),
            }
            for r in (result.reasons or [])
            if str(r.detail or "").strip()
        ]
        if len(reasons) < 2:
            logger.warning("Idea scan brief for %s had too few reasons", ticker)
            return None

        stance = str(result.portfolio_fit.stance or "neutral").strip().lower()
        if stance not in ("diversifies", "neutral", "concentrated"):
            stance = "neutral"
        warning = result.portfolio_fit.warning
        warning_s = str(warning).strip() if warning else None

        brief = {
            "thesis": str(result.thesis or "").strip(),
            "reasons": reasons[:5],
            "sources": sources[:8],
            "portfolio_fit": {
                "stance": stance,
                "warning": warning_s,
                "note": str(result.portfolio_fit.note or "").strip(),
            },
        }
        if not brief["thesis"]:
            return None

        company_name = (
            str(result.company_name or "").strip()
            or str(candidate.get("name") or "").strip()
            or ticker
        )
        company_blurb = str(result.company_blurb or "").strip()
        if not company_blurb:
            company_blurb = f"{company_name} — see brief for why it appeared in suggestions."

        return {
            "ticker": ticker,
            "reason": ranked["reason"],
            "source": ranked.get("source"),
            "company_name": company_name,
            "company_blurb": company_blurb[:400],
            "sector": str(result.sector or profile.get("finnhubIndustry") or "").strip()
            or None,
            "industry": str(result.industry or profile.get("finnhubIndustry") or "").strip()
            or None,
            "brief": brief,
        }
