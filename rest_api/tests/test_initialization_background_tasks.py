import asyncio
from unittest.mock import AsyncMock, patch
import pytest

from rest_api.main import run_pipeline, pipeline_in_interval


@patch("rest_api.main.analysis_service.run")
@patch("rag_graphs.news_rag_graph.ingestion.DocumentSyncManager.sync_documents")
@patch("scraper.scraper_factory.NewsScraperFactory.create_scraper")
@patch("scraper.scraper_factory.StockScraperFactory.create_scraper")
@patch("rest_api.main.get_scrape_tickers", return_value=["AAPL"])
@pytest.mark.asyncio
async def test_run_pipeline(mock_tickers, mock_stock_factory, mock_news_factory, mock_sync, mock_analysis):
    mock_news_factory.return_value.scrape_all_tickers = lambda x: None
    mock_stock_factory.return_value.scrape_all_tickers = lambda x: None

    await run_pipeline()
    mock_sync.assert_called_once()
    mock_analysis.assert_called_once()


@patch("rest_api.main.asyncio.sleep", new_callable=AsyncMock)
@patch("rest_api.main.run_pipeline")
@pytest.mark.asyncio
async def test_pipeline_in_interval(mock_run_pipeline, mock_sleep):
    mock_run_pipeline.return_value = None
    mock_sleep.side_effect = [None, asyncio.CancelledError()]
    with pytest.raises(asyncio.CancelledError):
        await pipeline_in_interval()
    mock_run_pipeline.assert_called_once()
