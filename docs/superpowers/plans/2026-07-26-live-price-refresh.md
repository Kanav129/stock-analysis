# Live Price Refresh — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** During US RTH with tab visible, every 5 min backfill on-screen tickers’ `1m` bars from Yahoo and refresh quotes/chart.

**Architecture:** Thin `POST /stock/prices/live-refresh` → `StockDataScraper.refresh_live_1m` → FE hook gated by visibility + NYSE RTH.

**Tech Stack:** FastAPI, yfinance, React Query, `America/New_York` session check.

---

### Task 1: Scraper + API

- [x] `refresh_live_1m` on scraper (`period=1d`, fallback `2d`)
- [x] `POST /stock/prices/live-refresh` (before `/{ticker}` routes)
- [x] Skip when sync running; cap 40 tickers
- [x] Unit tests

### Task 2: Frontend hook + wire-up

- [x] `isUsRegularHours` + `useLivePriceRefresh`
- [x] Dashboard + Stock detail
- [x] `api.livePriceRefresh`

### Task 3: Verify

- [x] pytest + tsc
