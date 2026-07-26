# Price Interval Ladder — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store multi-resolution OHLCV bars, compact on sync, and serve charts from the matching interval.

**Architecture:** `StockDataScraper` gap-fills bands (`1m`/`15m`/`30m`/`1h`/`1d`), aggregates aged fines into coarser bands, deletes expired fines. Chart API picks interval by duration with coarser fallbacks. One-time migrate deletes legacy `5m`.

**Tech Stack:** yfinance, Postgres `stock_data`, FastAPI chart route, React chart range toggle.

---

### Task 1: Scraper ladder

**Files:**
- Modify: `scraper/stock_data_scraper.py`
- Test: `scraper/tests/test_stock_data_scraper.py`

- [x] Band config, sync_band, compact_ladder, migrate_legacy_5m
- [x] Unit tests for upsert, sync period selection, snap helpers

### Task 2: Chart API

**Files:**
- Modify: `rest_api/routes/stock_routes.py`

- [x] Map duration → interval (`1→1m`, `7→15m`, `14→30m`, `30→1h`, else `1d`)
- [x] Fallback chain when band empty

### Task 3: Frontend + docs

**Files:**
- Modify: `frontend/src/components/ChartRangeToggle.tsx`
- Modify: `README.md`
- Modify: `rag_graphs/.../sql_generation_chain.py`
- Modify: `db/models/stock_data.py`
- Spec: `docs/superpowers/specs/2026-07-26-price-interval-ladder-design.md`

- [x] Range hints match ladder
- [x] README / SQL RAG / model comments updated

### Task 4: Verify

- [x] `pytest scraper/tests/test_stock_data_scraper.py` (10 passed)
- [ ] Next daily sync migrates `5m` and fills new bands (runtime)
