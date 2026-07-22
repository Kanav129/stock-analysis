import asyncio
from unittest.mock import MagicMock, patch

from services.sync_service import SyncService


def _close_scheduled_coroutine(create_task: MagicMock) -> None:
    coroutine = create_task.call_args.args[0]
    coroutine.close()


def test_start_returns_already_completed_today():
    svc = SyncService()
    universe = ["AAPL", "MSFT"]
    cp = {
        "status": "completed",
        "news_done": universe,
        "prices_done": universe,
        "vectors_done": True,
        "finished_at": "2026-07-22T01:00:00+00:00",
    }

    with (
        patch.object(svc.universe, "get_tickers", return_value=universe),
        patch("services.sync_service.rcs.load_sync", return_value=cp),
        patch("services.sync_service.rcs.today_key", return_value="2026-07-22"),
        patch(
            "services.sync_service.rcs.is_sync_complete_for_universe",
            return_value=True,
        ),
        patch(
            "services.sync_service.rcs.daily_sync_summary",
            return_value={"status": "completed"},
        ),
    ):
        result = svc.start(force=False)

    assert result["started"] is False
    assert result["reason"] == "already_completed_today"
    assert result["date"] == "2026-07-22"
    assert result["finished_at"] == cp["finished_at"]
    assert result["daily"] == {"status": "completed"}


def test_start_force_clears_and_starts():
    svc = SyncService()
    universe = ["AAPL"]
    cp = {
        "status": "completed",
        "news_done": universe,
        "prices_done": universe,
        "vectors_done": True,
    }
    saved = {}

    def fake_save(data, day=None):
        saved["cp"] = dict(data)

    with (
        patch.object(svc.universe, "get_tickers", return_value=universe),
        patch("services.sync_service.rcs.load_sync", return_value=cp),
        patch("services.sync_service.rcs.save_sync", side_effect=fake_save),
        patch("services.sync_service.rcs.today_key", return_value="2026-07-22"),
        patch(
            "services.sync_service.rcs.is_sync_complete_for_universe",
            return_value=True,
        ),
        patch(
            "services.sync_service.rcs.sync_todos",
            return_value={
                "news_todo": universe,
                "prices_todo": universe,
                "need_vectors": True,
                "resumed": False,
                "cleared": True,
            },
        ),
        patch("asyncio.get_running_loop") as loop,
    ):
        loop.return_value.create_task = MagicMock()
        result = svc.start(force=True)
        _close_scheduled_coroutine(loop.return_value.create_task)

    assert result["started"] is True
    assert result["resumed"] is False
    assert result["skipped"] == {"news": 0, "prices": 0}
    assert saved["cp"]["news_done"] == []
    assert saved["cp"]["prices_done"] == []
    assert saved["cp"]["vectors_done"] is False


def test_start_resumes_todos_and_sizes_timeouts_from_remaining_counts():
    svc = SyncService()
    universe = ["AAPL", "MSFT", "NVDA"]
    cp = {
        "status": "partial",
        "news_done": ["AAPL", "MSFT"],
        "prices_done": ["AAPL"],
        "vectors_done": False,
    }

    with (
        patch.object(svc.universe, "get_tickers", return_value=universe),
        patch("services.sync_service.rcs.load_sync", return_value=cp),
        patch("services.sync_service.rcs.save_sync"),
        patch("services.sync_service.rcs.today_key", return_value="2026-07-22"),
        patch(
            "services.sync_service.rcs.is_sync_complete_for_universe",
            return_value=False,
        ),
        patch(
            "services.sync_service.rcs.sync_todos",
            return_value={
                "news_todo": ["NVDA"],
                "prices_todo": ["MSFT", "NVDA"],
                "need_vectors": True,
                "resumed": True,
                "cleared": False,
            },
        ),
        patch("services.sync_service.compute_stage_timeouts") as compute,
        patch("asyncio.get_running_loop") as loop,
    ):
        compute.side_effect = [
            {"news": 301, "prices": 901, "vectors": 600, "total": 1802},
            {"news": 302, "prices": 902, "vectors": 600, "total": 1804},
        ]
        loop.return_value.create_task = MagicMock()
        result = svc.start()

    assert result["started"] is True
    assert result["resumed"] is True
    assert result["skipped"] == {"news": 2, "prices": 1}
    assert result["timeouts"] == {
        "news": 301,
        "prices": 902,
        "vectors": 600,
        "total": 1803,
    }
    assert compute.call_args_list[0].args == (1,)
    assert compute.call_args_list[1].args == (2,)
    worker_args = loop.return_value.create_task.call_args.args[0]
    assert worker_args.cr_frame.f_locals["news_todo"] == ["NVDA"]
    assert worker_args.cr_frame.f_locals["prices_todo"] == ["MSFT", "NVDA"]
    _close_scheduled_coroutine(loop.return_value.create_task)


def test_get_status_embeds_daily_summary():
    svc = SyncService()
    svc._status["tickers"] = ["AAPL"]
    cp = {"status": "partial", "news_done": ["AAPL"]}
    daily = {"status": "partial", "can_resume": True}

    with (
        patch("services.sync_service.rcs.load_sync", return_value=cp),
        patch(
            "services.sync_service.rcs.daily_sync_summary",
            return_value=daily,
        ) as summarize,
    ):
        result = svc.get_status()

    assert result["daily"] == daily
    summarize.assert_called_once_with(cp, ["AAPL"])


def test_worker_checkpoints_each_ticker_and_completes():
    svc = SyncService()
    svc._running = True
    cp = {
        "status": "running",
        "tickers": ["AAPL"],
        "news_done": [],
        "prices_done": [],
        "vectors_done": False,
        "errors": [],
    }
    news = MagicMock()
    prices = MagicMock()
    news.scrape_all_tickers.side_effect = (
        lambda tickers, on_progress=None, on_ticker_done=None: on_ticker_done("AAPL")
    )
    prices.scrape_all_tickers.side_effect = (
        lambda tickers, on_progress=None, on_ticker_done=None: on_ticker_done("AAPL")
    )
    vector_manager = MagicMock()
    snapshots = []
    saved_days = []

    with (
        patch(
            "services.sync_service.NewsScraperFactory.create_scraper",
            return_value=news,
        ),
        patch(
            "services.sync_service.StockScraperFactory.create_scraper",
            return_value=prices,
        ),
        patch("services.sync_service.DocumentSyncManager", return_value=vector_manager),
        patch(
            "services.sync_service.rcs.save_sync",
            side_effect=lambda data, day=None: (
                snapshots.append(dict(data)),
                saved_days.append(day),
            ),
        ),
        patch(
            "services.sync_service.rcs.is_sync_complete_for_universe",
            return_value=True,
        ),
        patch("services.sync_service.rcs.mark_last_sync_date") as mark_last,
    ):
        asyncio.run(
            svc._run_worker(
                ["AAPL"],
                ["AAPL"],
                ["AAPL"],
                True,
                checkpoint_seed=cp,
                day="2026-07-22",
            )
        )

    assert any(item["news_done"] == ["AAPL"] for item in snapshots)
    assert any(item["prices_done"] == ["AAPL"] for item in snapshots)
    assert snapshots[-1]["status"] == "completed"
    assert snapshots[-1]["vectors_done"] is True
    assert saved_days and set(saved_days) == {"2026-07-22"}
    mark_last.assert_called_once_with("2026-07-22")
    assert svc.get_status()["status"] == "completed"


def test_worker_vector_failure_stays_partial_and_does_not_mark_last_sync():
    svc = SyncService()
    svc._running = True
    cp = {
        "status": "running",
        "tickers": ["AAPL"],
        "news_done": ["AAPL"],
        "prices_done": ["AAPL"],
        "vectors_done": False,
        "errors": [],
    }
    vector_manager = MagicMock()
    vector_manager.sync_documents.side_effect = RuntimeError("vector store unavailable")
    snapshots = []

    with (
        patch("services.sync_service.NewsScraperFactory") as news_factory,
        patch("services.sync_service.StockScraperFactory") as stock_factory,
        patch("services.sync_service.DocumentSyncManager", return_value=vector_manager),
        patch(
            "services.sync_service.rcs.save_sync",
            side_effect=lambda data, day=None: snapshots.append(dict(data)),
        ),
        patch("services.sync_service.rcs.mark_last_sync_date") as mark_last,
    ):
        asyncio.run(
            svc._run_worker(
                ["AAPL"],
                [],
                [],
                True,
                checkpoint_seed=cp,
                day="2026-07-22",
            )
        )

    assert snapshots[-1]["status"] == "partial"
    assert snapshots[-1]["vectors_done"] is False
    assert svc.get_status()["status"] != "completed"
    assert svc.get_status()["percent"] < 100
    assert svc.last_sync is None
    mark_last.assert_not_called()
    news_factory.assert_not_called()
    stock_factory.assert_not_called()


def test_worker_keeps_incomplete_coverage_partial():
    svc = SyncService()
    svc._running = True
    cp = {
        "status": "running",
        "tickers": ["AAPL", "MSFT"],
        "news_done": ["AAPL"],
        "prices_done": ["AAPL", "MSFT"],
        "vectors_done": True,
        "errors": [],
    }
    news = MagicMock()
    snapshots = []

    with (
        patch(
            "services.sync_service.NewsScraperFactory.create_scraper",
            return_value=news,
        ),
        patch("services.sync_service.StockScraperFactory") as stock_factory,
        patch(
            "services.sync_service.rcs.save_sync",
            side_effect=lambda data, day=None: snapshots.append((dict(data), day)),
        ),
        patch(
            "services.sync_service.rcs.is_sync_complete_for_universe",
            return_value=False,
        ) as is_complete,
        patch("services.sync_service.rcs.mark_last_sync_date") as mark_last,
    ):
        asyncio.run(
            svc._run_worker(
                ["AAPL", "MSFT"],
                ["MSFT"],
                [],
                False,
                checkpoint_seed=cp,
                day="2026-07-22",
            )
        )

    is_complete.assert_called_once()
    stock_factory.assert_not_called()
    assert snapshots[-1][0]["status"] == "partial"
    assert snapshots[-1][1] == "2026-07-22"
    assert "some tickers" in svc.get_status()["message"].lower()
    assert svc.get_status()["percent"] < 100
    assert svc.last_sync is None
    mark_last.assert_not_called()


def test_worker_constructs_only_price_scraper_for_price_only_resume():
    svc = SyncService()
    svc._running = True
    cp = {
        "status": "running",
        "tickers": ["AAPL"],
        "news_done": ["AAPL"],
        "prices_done": [],
        "vectors_done": True,
        "errors": [],
    }
    prices = MagicMock()
    prices.scrape_all_tickers.side_effect = (
        lambda tickers, on_progress=None, on_ticker_done=None: on_ticker_done("AAPL")
    )

    with (
        patch("services.sync_service.NewsScraperFactory") as news_factory,
        patch(
            "services.sync_service.StockScraperFactory.create_scraper",
            return_value=prices,
        ),
        patch("services.sync_service.rcs.save_sync"),
        patch(
            "services.sync_service.rcs.is_sync_complete_for_universe",
            return_value=True,
        ),
        patch("services.sync_service.rcs.mark_last_sync_date"),
    ):
        asyncio.run(
            svc._run_worker(
                ["AAPL"],
                [],
                ["AAPL"],
                False,
                checkpoint_seed=cp,
                day="2026-07-22",
            )
        )

    news_factory.assert_not_called()


def test_start_passes_pinned_day_to_worker():
    svc = SyncService()

    with (
        patch.object(svc.universe, "get_tickers", return_value=["AAPL"]),
        patch("services.sync_service.rcs.today_key", return_value="2026-07-22"),
        patch("services.sync_service.rcs.load_sync", return_value=None) as load_sync,
        patch(
            "services.sync_service.rcs.sync_todos",
            return_value={
                "news_todo": ["AAPL"],
                "prices_todo": ["AAPL"],
                "need_vectors": True,
                "resumed": False,
            },
        ),
        patch("services.sync_service.rcs.save_sync"),
        patch("asyncio.get_running_loop") as loop,
    ):
        loop.return_value.create_task = MagicMock()
        svc.start()
        worker = loop.return_value.create_task.call_args.args[0]
        assert worker.cr_frame.f_locals["day"] == "2026-07-22"
        _close_scheduled_coroutine(loop.return_value.create_task)
        assert load_sync.call_args_list[0].args == ("2026-07-22",)
