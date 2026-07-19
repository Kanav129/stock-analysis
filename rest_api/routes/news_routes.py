from fastapi import APIRouter, HTTPException, Query
from rag_graphs.news_rag_graph.graph.graph import app
from services.news_service import NewsService

router = APIRouter()
news_service = NewsService()


@router.get("/{ticker}/articles")
def recent_articles(
    ticker: str,
    limit: int = Query(10, ge=1, le=50, description="Max articles to return"),
):
    """Recent scraped news headlines for a ticker from MongoDB."""
    try:
        articles = news_service.get_recent_articles(ticker, limit=limit)
        return {"ticker": ticker.upper(), "articles": articles}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{ticker}")
def news_by_topic(
    ticker: str,
    # Optional query parameter
    topic: str  = Query(None, description="Topic"),
):
    """
    Get news a specific ticker.

    Args:
        ticker (str): Stock ticker symbol.
        topic (str): Topic to fetch news for a specific stock.

    Returns:
        dict: Relevant news for a speicific ticker.
    """

    try:

        if topic:
            human_query = f"News related to {topic} for {ticker}"
        else:
            human_query = f"News related to {ticker}"

        res         = app.invoke({"question": human_query})
        return {
            "ticker": ticker,
            "topic": topic,
            "result": res["generation"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))