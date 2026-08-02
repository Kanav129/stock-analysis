"""IBKR Flex Web Service v3 client — pull Open Positions as XML."""
from __future__ import annotations

import os
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Optional
from xml.etree.ElementTree import Element

import requests

from utils.logger import logger

SEND_REQUEST_URL = (
    "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest"
)
GET_STATEMENT_URL = (
    "https://gdcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement"
)
USER_AGENT = "stocks-insights-ai-agent/1.0"

# v1: stocks and ETFs only (case-insensitive assetCategory values).
EQUITY_ASSET_CLASSES = frozenset(
    {
        "STK",
        "STOCK",
        "STOCKS",
        "ETF",
        "ETFS",
        "EQUITY",
        "EQUITIES",
    }
)


class FlexConfigError(Exception):
    """Missing or invalid Flex credentials / configuration."""


class FlexUpstreamError(Exception):
    """IBKR Flex request failed or timed out."""


@dataclass
class FlexPosition:
    ticker: str
    quantity: float
    avg_cost: Optional[float]
    account_id: str
    currency: str
    conid: Optional[str] = None
    asset_class: Optional[str] = None
    description: Optional[str] = None
    exchange: Optional[str] = None
    side: Optional[str] = None
    multiplier: Optional[float] = None
    report_date: Optional[str] = None
    ibkr_mark_price: Optional[float] = None
    ibkr_position_value: Optional[float] = None
    cost_basis_money: Optional[float] = None
    cost_basis_price: Optional[float] = None
    ibkr_unrealized_pnl: Optional[float] = None
    percent_of_nav: Optional[float] = None
    fx_rate_to_base: Optional[float] = None
    raw_symbol: Optional[str] = None
    source_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class FlexParseResult:
    positions: list[FlexPosition]
    skipped: int
    skipped_asset_classes: dict[str, int] = field(default_factory=dict)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _attr(el: Element, *names: str) -> Optional[str]:
    for name in names:
        val = el.attrib.get(name)
        if val is not None and str(val).strip() != "":
            return str(val).strip()
    # Case-insensitive fallback
    lower_map = {k.lower(): v for k, v in el.attrib.items()}
    for name in names:
        val = lower_map.get(name.lower())
        if val is not None and str(val).strip() != "":
            return str(val).strip()
    return None


def _float_attr(el: Element, *names: str) -> Optional[float]:
    raw = _attr(el, *names)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def normalize_ibkr_symbol(symbol: str) -> str:
    """Normalize IBKR symbols to desk tickers (e.g. BRK B → BRK.B)."""
    s = (symbol or "").strip().upper()
    if not s:
        return s
    parts = s.split()
    # Share class: "BRK B" → "BRK.B"
    if len(parts) == 2 and len(parts[1]) == 1 and parts[1].isalpha():
        return f"{parts[0]}.{parts[1]}"
    # Drop exchange / currency tokens: "AAPL US" → "AAPL"
    if len(parts) >= 2:
        return parts[0]
    return parts[0].replace(" ", ".") if parts else s.replace(" ", ".")


def is_equity_asset_class(asset_class: Optional[str]) -> bool:
    if not asset_class:
        return False
    return asset_class.strip().upper() in EQUITY_ASSET_CLASSES


def parse_flex_statement(xml_text: str) -> FlexParseResult:
    """Parse Flex statement XML into stock/ETF positions."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise FlexUpstreamError(f"Malformed Flex statement XML: {exc}") from exc

    # Error envelope: <FlexStatementResponse><Status>Fail</Status>...
    status = root.findtext("Status") or root.attrib.get("status")
    if status and status.strip().lower() == "fail":
        err = root.findtext("ErrorMessage") or root.findtext("ErrorCode") or "unknown"
        raise FlexUpstreamError(f"Flex statement error: {err}")

    positions: list[FlexPosition] = []
    skipped = 0
    skipped_classes: dict[str, int] = {}

    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag != "OpenPosition":
            continue
        asset = _attr(el, "assetCategory", "assetClass", "AssetCategory")
        if not is_equity_asset_class(asset):
            skipped += 1
            key = (asset or "unknown").upper()
            skipped_classes[key] = skipped_classes.get(key, 0) + 1
            continue

        raw_symbol = _attr(el, "symbol", "Symbol") or ""
        ticker = normalize_ibkr_symbol(raw_symbol)
        qty = _float_attr(el, "position", "quantity", "Quantity", "Position")
        if not ticker or qty is None or qty == 0:
            skipped += 1
            continue

        cost_price = _float_attr(
            el, "costBasisPrice", "CostBasisPrice", "openPrice", "OpenPrice"
        )
        source_data = dict(el.attrib)

        positions.append(
            FlexPosition(
                ticker=ticker,
                quantity=float(qty),
                avg_cost=cost_price,
                account_id=_attr(el, "clientAccountId", "accountId", "AccountId")
                or "default",
                currency=_attr(el, "currencyPrimary", "currency", "Currency") or "USD",
                conid=_attr(el, "conid", "conId", "Conid"),
                asset_class=asset.upper() if asset else None,
                description=_attr(el, "description", "description1", "Description"),
                exchange=_attr(el, "listingExchange", "exchange", "ListingExchange"),
                side=_attr(el, "side", "Side"),
                multiplier=_float_attr(el, "multiplier", "Multiplier"),
                report_date=_attr(el, "reportDate", "ReportDate"),
                ibkr_mark_price=_float_attr(el, "markPrice", "MarkPrice"),
                ibkr_position_value=_float_attr(el, "positionValue", "PositionValue"),
                cost_basis_money=_float_attr(el, "costBasisMoney", "CostBasisMoney"),
                cost_basis_price=cost_price,
                ibkr_unrealized_pnl=_float_attr(
                    el, "fifoPnlUnrealized", "FifoPnlUnrealized", "unrealizedPnl"
                ),
                percent_of_nav=_float_attr(el, "percentOfNAV", "PercentOfNAV"),
                fx_rate_to_base=_float_attr(el, "fxRateToBase", "FxRateToBase"),
                raw_symbol=raw_symbol,
                source_data=source_data,
            )
        )

    return FlexParseResult(
        positions=positions,
        skipped=skipped,
        skipped_asset_classes=skipped_classes,
    )


def _parse_send_request(xml_text: str) -> tuple[str, Optional[str]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise FlexUpstreamError(f"Malformed Flex SendRequest XML: {exc}") from exc

    status = (root.findtext("Status") or root.attrib.get("status") or "").strip()
    if status.lower() == "fail":
        err = root.findtext("ErrorMessage") or root.findtext("ErrorCode") or "unknown"
        # Never echo token-bearing URLs; message text from IBKR is usually safe.
        raise FlexUpstreamError(f"Flex SendRequest failed: {err}")

    ref = root.findtext("ReferenceCode") or root.attrib.get("ReferenceCode")
    if not ref:
        raise FlexUpstreamError("Flex SendRequest missing ReferenceCode")
    url = root.findtext("Url") or root.findtext("url")
    return str(ref).strip(), (str(url).strip() if url else None)


def _is_statement_pending(xml_text: str) -> bool:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return False
    status = (root.findtext("Status") or "").strip().lower()
    if status == "warn" or status == "pending":
        return True
    code = (root.findtext("ErrorCode") or "").strip()
    # IBKR: 1019 / 1018 often mean statement not ready yet
    if code in {"1018", "1019"}:
        return True
    msg = (root.findtext("ErrorMessage") or "").lower()
    if "generation in progress" in msg or "please try again" in msg:
        return True
    return False


class IbkrFlexClient:
    """HTTP client for Flex Web Service v3."""

    def __init__(
        self,
        token: str | None = None,
        query_id: str | None = None,
        *,
        session: requests.Session | None = None,
    ) -> None:
        self.token = (token if token is not None else os.getenv("IBKR_FLEX_TOKEN") or "").strip()
        self.query_id = (
            query_id if query_id is not None else os.getenv("IBKR_FLEX_QUERY_ID") or ""
        ).strip()
        self.timeout = _env_float("IBKR_FLEX_TIMEOUT_SECONDS", 30.0)
        self.poll_interval = _env_float("IBKR_FLEX_POLL_INTERVAL_SECONDS", 2.0)
        self.max_polls = _env_int("IBKR_FLEX_MAX_POLLS", 30)
        self._session = session or requests.Session()

    def ensure_configured(self) -> None:
        if not self.token or not self.query_id:
            raise FlexConfigError(
                "IBKR Flex is not configured. Set IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID."
            )

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": USER_AGENT}

    def send_request(self) -> tuple[str, Optional[str]]:
        self.ensure_configured()
        try:
            resp = self._session.get(
                SEND_REQUEST_URL,
                params={"t": self.token, "q": self.query_id, "v": "3"},
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise FlexUpstreamError(f"Flex SendRequest network error: {exc}") from exc
        if resp.status_code >= 400:
            raise FlexUpstreamError(
                f"Flex SendRequest HTTP {resp.status_code}"
            )
        return _parse_send_request(resp.text)

    def get_statement(self, reference_code: str, url: str | None = None) -> str:
        self.ensure_configured()
        endpoint = (url or GET_STATEMENT_URL).strip() or GET_STATEMENT_URL
        last_pending = ""
        for attempt in range(1, self.max_polls + 1):
            try:
                resp = self._session.get(
                    endpoint,
                    params={"t": self.token, "q": reference_code, "v": "3"},
                    headers=self._headers(),
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                raise FlexUpstreamError(f"Flex GetStatement network error: {exc}") from exc
            text = resp.text
            if resp.status_code >= 400:
                raise FlexUpstreamError(f"Flex GetStatement HTTP {resp.status_code}")
            if _is_statement_pending(text):
                last_pending = text[:200]
                logger.info(
                    "Flex statement pending (attempt %s/%s)", attempt, self.max_polls
                )
                time.sleep(self.poll_interval)
                continue
            # Ready statement contains OpenPosition or FlexQueryResponse / FlexStatement
            if "<OpenPosition" in text or "FlexQueryResponse" in text or "FlexStatement" in text:
                return text
            # Fail envelope after pending checks
            try:
                root = ET.fromstring(text)
                status = (root.findtext("Status") or "").strip().lower()
                if status == "fail":
                    err = root.findtext("ErrorMessage") or "unknown"
                    raise FlexUpstreamError(f"Flex GetStatement failed: {err}")
            except ET.ParseError as exc:
                raise FlexUpstreamError(f"Malformed Flex GetStatement XML: {exc}") from exc
            # Unknown but parseable — treat as ready
            return text

        raise FlexUpstreamError(
            f"Flex statement not ready after {self.max_polls} polls"
            + (f" ({last_pending})" if last_pending else "")
        )

    def download_positions(self) -> FlexParseResult:
        """SendRequest → poll GetStatement → parse OpenPositions."""
        ref, url = self.send_request()
        logger.info("Flex SendRequest ok (reference received)")
        xml_text = self.get_statement(ref, url)
        result = parse_flex_statement(xml_text)
        logger.info(
            "Flex parsed %s equity position(s), skipped %s",
            len(result.positions),
            result.skipped,
        )
        return result
