import asyncio
from unittest.mock import AsyncMock, patch
import pytest

from rest_api.main import run_pipeline, run_sync_job, sync_in_interval


@patch("rest_api.main.analysis_service.run")
@patch("rest_api.main.sync_service.sync_data", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_run_pipeline(mock_sync, mock_analysis):
    mock_sync.return_value = {"started": True, "tickers": ["AAPL"], "message": "ok"}
    mock_analysis.return_value = {"status": "completed"}

    with patch("rest_api.main.get_scrape_tickers", return_value=["AAPL"]):
        await run_pipeline()

    mock_sync.assert_called_once()
    mock_analysis.assert_called_once_with(["AAPL"])


@patch("rest_api.main.sync_service.sync_data", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_run_sync_job(mock_sync):
    mock_sync.return_value = {"started": True, "tickers": ["AAPL"], "message": "ok"}
    await run_sync_job()
    mock_sync.assert_called_once()


@patch("rest_api.main.asyncio.sleep", new_callable=AsyncMock)
@patch("rest_api.main.run_sync_job", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_sync_in_interval(mock_run_sync, mock_sleep):
    mock_run_sync.return_value = None
    mock_sleep.side_effect = [None, asyncio.CancelledError()]
    with pytest.raises(asyncio.CancelledError):
        await sync_in_interval()
    mock_run_sync.assert_called_once()
