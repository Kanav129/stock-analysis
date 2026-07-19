from fastapi import APIRouter, HTTPException, Query

from db.db_factory import get_db_client
from rag_graphs.stock_data_rag_graph.graph.graph import app as stock_data_graph
from services.quotes_service import QuotesService

router = APIRouter()

ALLOWED_PRICE_COLUMNS = {"open", "close", "low", "high"}
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


@router.get("/{ticker}/chart")
def chart(
    ticker: str,
    price_type: str = Query("close", description="Price type: 'open', 'close', 'low', 'high'"),
    duration: str = Query("90", description="Days (1, 7, 15, 30, …) or 'all'"),
):
    """Return chart series: 5m bars for 1D, daily closes otherwise (deduped)."""
    try:
        price_col = price_type.lower()
        if price_col not in ALLOWED_PRICE_COLUMNS:
            raise HTTPException(status_code=400, detail=f"Invalid price_type: {price_type}")

        duration_days = _parse_chart_duration(duration)
        db = get_db_client()
        symbol = ticker.upper()

        # Intraday chart for 1 day; daily closes for longer ranges (no duplicate days)
        if duration_days is not None and duration_days <= 1:
            rows, cols = db.fetch_query(
                f"""
                SELECT bar_ts AS date, {price_col}
                FROM stock_data
                WHERE ticker = %s
                  AND bar_interval = '5m'
                  AND bar_ts >= NOW() - INTERVAL '1 day'
                ORDER BY bar_ts ASC
                """,
                (symbol,),
            )
            if not rows:
                rows, cols = db.fetch_query(
                    f"""
                    SELECT date, {price_col}
                    FROM stock_data
                    WHERE ticker = %s
                      AND bar_interval = '1d'
                      AND date >= CURRENT_DATE - INTERVAL '5 days'
                    ORDER BY date ASC
                    """,
                    (symbol,),
                )
        elif duration_days is None:
            rows, cols = db.fetch_query(
                f"""
                SELECT DISTINCT ON (date) date, {price_col}
                FROM stock_data
                WHERE ticker = %s
                ORDER BY date ASC,
                         CASE WHEN bar_interval = '1d' THEN 0 ELSE 1 END,
                         bar_ts DESC
                """,
                (symbol,),
            )
        else:
            rows, cols = db.fetch_query(
                f"""
                SELECT DISTINCT ON (date) date, {price_col}
                FROM stock_data
                WHERE ticker = %s
                  AND date >= CURRENT_DATE - %s * INTERVAL '1 day'
                ORDER BY date ASC,
                         CASE WHEN bar_interval = '1d' THEN 0 ELSE 1 END,
                         bar_ts DESC
                """,
                (symbol, duration_days),
            )

        records = []
        for row in rows:
            record = dict(zip(cols, row))
            if record.get("date") and hasattr(record["date"], "isoformat"):
                record["date"] = record["date"].isoformat()
            records.append(record)

        return {
            "ticker": ticker,
            "price_type": price_type,
            "duration": duration,
            "result": records,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
