from fastapi import APIRouter, HTTPException, Query

from db.db_factory import get_db_client
from rag_graphs.stock_data_rag_graph.graph.graph import app as stock_data_graph
from rest_api.schemas import LivePriceRefreshRequest
from scraper.stock_data_scraper import StockDataScraper
from services.live_refresh_service import is_yahoo_rate_limit, live_refresh_service
from services.quotes_service import QuotesService
from services.sync_service import sync_service
from utils.logger import logger

router = APIRouter()

ALLOWED_PRICE_COLUMNS = {"open", "close", "low", "high"}
LIVE_REFRESH_MAX_TICKERS = 40
quotes_service = QuotesService()


@router.get("/quotes")
def quotes(
    tickers: str = Query(..., description="Comma-separated tickers, e.g. AAPL,MSFT,SPY"),
    spark_days: int = Query(30, ge=5, le=120),
):
    """Latest close, prior close, day change %, and sparkline series for many tickers."""
    symbols = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not symbols:
        raise HTTPException(status_code=400, detail="Provide at least one ticker")
    if len(symbols) > 80:
        raise HTTPException(status_code=400, detail="Too many tickers (max 80)")
    data = quotes_service.get_quotes(symbols, spark_days=spark_days)
    return {"quotes": data}


@router.post("/prices/live-refresh")
def live_price_refresh(body: LivePriceRefreshRequest):
    """Backfill today's 1m bars for on-screen tickers (US RTH live desk)."""
    symbols = []
    seen: set[str] = set()
    for raw in body.tickers or []:
        t = (raw or "").strip().upper()
        if t and t not in seen:
            seen.add(t)
            symbols.append(t)
    if not symbols:
        raise HTTPException(status_code=400, detail="Provide at least one ticker")
    if len(symbols) > LIVE_REFRESH_MAX_TICKERS:
        raise HTTPException(
            status_code=400,
            detail=f"Too many tickers (max {LIVE_REFRESH_MAX_TICKERS})",
        )

    if sync_service.is_running:
        return {"skipped": True, "reason": "sync_running", "results": {}}

    pause_until = live_refresh_service.pause_until_iso()
    if pause_until is not None:
        logger.info("live-refresh paused until %s (Yahoo rate limit)", pause_until)
        return {
            "skipped": True,
            "reason": "rate_limited",
            "pause_until": pause_until,
            "results": {},
        }

    if not live_refresh_service.try_begin():
        return {"skipped": True, "reason": "refresh_in_progress", "results": {}}

    scraper = StockDataScraper()
    results: dict[str, object] = {}
    try:
        for symbol in symbols:
            try:
                results[symbol] = {"upserted": scraper.refresh_live_1m(symbol)}
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"live-refresh {symbol} failed: {exc}")
                results[symbol] = {"error": str(exc)}
                if is_yahoo_rate_limit(exc):
                    pause_until = live_refresh_service.record_rate_limit()
                    logger.warning(
                        "live-refresh paused until %s after Yahoo rate limit on %s",
                        pause_until,
                        symbol,
                    )
                    return {
                        "skipped": False,
                        "rate_limited": True,
                        "pause_until": pause_until,
                        "results": results,
                    }
    finally:
        live_refresh_service.end()

    return {"skipped": False, "results": results}


@router.get("/{ticker}/technicals")
def technicals(ticker: str):
    """RSI, MACD, moving averages, 52w range, ATR from local stock_data."""
    return quotes_service.get_technicals(ticker.upper())


@router.get("/{ticker}/price-stats")
def price_stats(
    ticker: str,
    operation: str  = Query(..., description="Operation to perform: 'highest', 'lowest', 'average'"),
    price_type: str = Query(..., description="Price type: 'open', 'close', 'low', 'high'"),
    duration :str   = Query(..., description="Duration (days): '1', '7', '14', '30'"),
):
    """
    Get stock price statistics for a specific ticker.

    Args:
        ticker (str): Stock ticker symbol.
        operation (str): Operation to perform (e.g., 'highest', 'lowest', 'average').
        price_type (str): Type of price (e.g., 'open', 'close', 'low', 'high').
        duration (int): Number of days

    Returns:
        dict: Stock data with the requested statistics.
    """

    try:
        human_query = f"What is the {operation} value of {price_type} for '{ticker}' over last {duration} day(s) ?"

        res         = stock_data_graph.invoke({"question": human_query})
        return {
            "ticker": ticker,
            "operation": operation,
            "price_type": price_type,
            "duration": duration,
            "result": res['generation']
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def _parse_chart_duration(duration: str) -> int | None:
    """Return day count, or None for full history ('all')."""
    raw = (duration or "").strip().lower()
    if raw in {"all", "max"}:
        return None
    try:
        days = int(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="duration must be a day count (e.g. 1, 7, 30) or 'all'",
        ) from exc
    if days < 1:
        raise HTTPException(status_code=400, detail="duration must be >= 1")
    return days


def _chart_interval_for_duration(duration_days: int | None) -> str:
    """Map UI range length to stored bar_interval ladder."""
    if duration_days is None or duration_days > 30:
        return "1d"
    if duration_days <= 1:
        return "1m"
    if duration_days <= 7:
        return "15m"
    if duration_days <= 14:
        return "30m"
    return "1h"


# Coarser fallbacks when a band is empty (e.g. mid-migration).
_INTERVAL_FALLBACKS = {
    "1m": ("15m", "30m", "1h", "1d"),
    "15m": ("30m", "1h", "1d"),
    "30m": ("1h", "1d"),
    "1h": ("1d",),
    "1d": (),
}


def _fetch_last_us_session(
    db,
    symbol: str,
    interval: str,
    price_col: str,
):
    """Bars for the latest US/Eastern trading date present in this interval.

    On weekends / before the next open, that date is typically Friday.
    """
    return db.fetch_query(
        f"""
        WITH latest AS (
            SELECT MAX(bar_ts) AS ts
            FROM stock_data
            WHERE ticker = %s AND bar_interval = %s
        ),
        sess AS (
            SELECT (ts AT TIME ZONE 'America/New_York')::date AS session_date
            FROM latest
            WHERE ts IS NOT NULL
        )
        SELECT s.bar_ts AS date, s.{price_col}
        FROM stock_data s
        CROSS JOIN sess
        WHERE s.ticker = %s
          AND s.bar_interval = %s
          AND (s.bar_ts AT TIME ZONE 'America/New_York')::date = sess.session_date
        ORDER BY s.bar_ts ASC
        """,
        (symbol, interval, symbol, interval),
    )


@router.get("/{ticker}/chart")
def chart(
    ticker: str,
    price_type: str = Query("close", description="Price type: 'open', 'close', 'low', 'high'"),
    duration: str = Query("90", description="Days (1, 7, 14, 30, …) or 'all'"),
):
    """Return chart series at the ladder interval for the requested range."""
    try:
        price_col = price_type.lower()
        if price_col not in ALLOWED_PRICE_COLUMNS:
            raise HTTPException(status_code=400, detail=f"Invalid price_type: {price_type}")

        duration_days = _parse_chart_duration(duration)
        db = get_db_client()
        symbol = ticker.upper()
        primary = _chart_interval_for_duration(duration_days)
        candidates = (primary,) + _INTERVAL_FALLBACKS.get(primary, ())

        rows, cols = [], []
        used_interval = primary
        session_date = None
        for interval in candidates:
            if duration_days == 1:
                rows, cols = _fetch_last_us_session(db, symbol, interval, price_col)
            elif interval == "1d" and duration_days is None:
                rows, cols = db.fetch_query(
                    f"""
                    SELECT bar_ts AS date, {price_col}
                    FROM stock_data
                    WHERE ticker = %s AND bar_interval = '1d'
                    ORDER BY bar_ts ASC
                    """,
                    (symbol,),
                )
            elif interval == "1d":
                rows, cols = db.fetch_query(
                    f"""
                    SELECT bar_ts AS date, {price_col}
                    FROM stock_data
                    WHERE ticker = %s
                      AND bar_interval = '1d'
                      AND bar_ts >= NOW() - (%s * INTERVAL '1 day')
                    ORDER BY bar_ts ASC
                    """,
                    (symbol, duration_days),
                )
            else:
                lookback = duration_days if duration_days is not None else 30
                rows, cols = db.fetch_query(
                    f"""
                    SELECT bar_ts AS date, {price_col}
                    FROM stock_data
                    WHERE ticker = %s
                      AND bar_interval = %s
                      AND bar_ts >= NOW() - (%s * INTERVAL '1 day')
                    ORDER BY bar_ts ASC
                    """,
                    (symbol, interval, lookback),
                )
            if rows:
                used_interval = interval
                break

        if duration_days == 1 and rows:
            # session_date from first bar in America/New_York
            first_ts = rows[0][0]
            try:
                from zoneinfo import ZoneInfo

                if getattr(first_ts, "tzinfo", None) is None:
                    first_ts = first_ts.replace(tzinfo=ZoneInfo("UTC"))
                session_date = first_ts.astimezone(ZoneInfo("America/New_York")).date().isoformat()
            except Exception:
                session_date = None

        records = []
        for row in rows:
            record = dict(zip(cols, row))
            if record.get("date") and hasattr(record["date"], "isoformat"):
                record["date"] = record["date"].isoformat()
            records.append(record)

        payload = {
            "ticker": ticker,
            "price_type": price_type,
            "duration": duration,
            "interval": used_interval,
            "result": records,
        }
        if session_date:
            payload["session_date"] = session_date
        return payload
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
