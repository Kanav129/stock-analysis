from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from rest_api.auth import AdminKeyMiddleware, auth_required, router as auth_router
from rest_api.routes import (
    stock_routes,
    news_routes,
    watchlist_routes,
    holdings_routes,
    analysis_routes,
    settings_routes,
    sync_routes,
    research_routes,
)
from db.bootstrap import bootstrap_schema
from services.analysis_service import analysis_service
from services.universe_service import UniverseService
from services.sync_service import sync_service
from services.settings_service import SettingsService
from utils.logger import logger
from datetime import datetime

import asyncio
import os

load_dotenv()

AUTO_PIPELINE_ENABLED = os.getenv("AUTO_PIPELINE_ENABLED", "true").lower() in ("1", "true", "yes")

_DEFAULT_CORS = "http://localhost:5173,http://127.0.0.1:5173"


def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", _DEFAULT_CORS)
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    return origins or _DEFAULT_CORS.split(",")


app = FastAPI(title="Personal Stock Analysis Dashboard")

# Auth is inner; CORS must be outermost so preflight succeeds.
app.add_middleware(AdminKeyMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

settings_service = SettingsService()
universe_service = UniverseService()


def get_scrape_tickers() -> list[str]:
    tickers = universe_service.get_tickers()
    if tickers:
        return tickers
    from config.config_loader import ConfigLoader
    config_loader = ConfigLoader(config_file="config/config.json")
    fallback = config_loader.get("SCRAPE_TICKERS", [])
    return fallback or []


async def run_pipeline():
    """Scrape news/prices for universe, sync vectors, then generate core reports + ratings."""
    result = await sync_service.sync_data()
    if not result.get("started") and not result.get("tickers"):
        logger.warning("No tickers to scrape.")
        return
    tickers = result.get("tickers") or get_scrape_tickers()
    if tickers:
        analysis_service.run(tickers)
    logger.info("Pipeline completed.")


@app.on_event("startup")
async def startup():
    if auth_required():
        logger.info("Admin key auth enabled (ADMIN_KEY is set).")
    else:
        logger.warning("Admin key auth disabled — set ADMIN_KEY to protect the API.")
    try:
        bootstrap_schema()
    except Exception as exc:
        logger.error(f"Schema bootstrap skipped or failed: {exc}")
    if AUTO_PIPELINE_ENABLED:
        asyncio.create_task(pipeline_in_interval())
    else:
        logger.info("Auto pipeline disabled (AUTO_PIPELINE_ENABLED=false). Use /sync/data and /analysis/run manually.")


async def pipeline_in_interval():
    while True:
        interval = settings_service.get_interval_seconds()
        hours = interval / 3600
        logger.info(f"Scheduled pipeline: next run in {hours:.2f} hours.")
        await asyncio.sleep(interval)
        logger.info(f"Starting scheduled pipeline at {datetime.now()}")
        try:
            await run_pipeline()
        except Exception as exc:
            logger.error(f"Pipeline failed: {exc}")
        logger.info("Scheduled pipeline completed.")


app.include_router(auth_router)
app.include_router(stock_routes.router, prefix="/stock", tags=["Stock Data"])
app.include_router(news_routes.router, prefix="/news", tags=["News Articles"])
app.include_router(watchlist_routes.router, tags=["Watchlist"])
app.include_router(holdings_routes.router, tags=["Holdings"])
app.include_router(analysis_routes.router, tags=["Analysis"])
app.include_router(settings_routes.router, tags=["Settings"])
app.include_router(sync_routes.router, tags=["Sync"])
app.include_router(research_routes.router, tags=["Research"])


@app.get("/")
def root():
    return {
        "message": "Personal Stock Analysis Dashboard API",
        "version": "1.0",
        "auth_required": auth_required(),
    }


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
