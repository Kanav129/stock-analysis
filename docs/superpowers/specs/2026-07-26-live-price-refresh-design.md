# Live price refresh (market hours, tab open)

**Date:** 2026-07-26  
**Status:** Approved  
**Scope:** Light Yahoo `1m` backfill for on-screen tickers every 5 minutes during US RTH

## Goals

1. While the desk tab is open during US regular hours, keep displayed prices fresh.
2. Each refresh backfills **today’s session `1m` bars** (Yahoo period covers the day + recent minutes).
3. Only refresh tickers currently on screen — not the full universe.

## Gates

| Gate | Rule |
|------|------|
| Tab | `document.visibilityState === 'visible'` |
| Session | Mon–Fri 09:30–16:00 `America/New_York` |
| Interval | Every 5 minutes; also once when gates become true |
| Sync | Skip while full `SyncService` is running |

## Tickers

- **Stock detail:** current ticker only  
- **Dashboard:** SPY/QQQ/IWM/DIA + holdings + watchlist shown on the page  
- Cap: 40 tickers per request  

## Backend

`POST /stock/prices/live-refresh`  
Body: `{ "tickers": ["AAPL", ...] }`  

Per ticker: `yfinance` history `interval=1m`, `period=1d` (fallback `2d` if empty), upsert into `stock_data`. No news, other bands, or compaction.  

If sync running → HTTP 200 `{ "skipped": true, "reason": "sync_running" }`.  
Auth: existing Bearer.

## Frontend

Hook `useLivePriceRefresh(tickers)` on Dashboard + Stock detail. After success, invalidate `quotes` and `chart`. Existing 60s quote DB poll stays.

## Non-goals

Pre/post market, websockets, full-universe live sync, changing daily GitHub cron.
