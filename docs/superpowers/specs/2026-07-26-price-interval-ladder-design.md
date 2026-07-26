# Multi-resolution price ladder (sync + charts)

**Date:** 2026-07-26  
**Status:** Approved  
**Scope:** Price sync compaction, chart API interval selection, one-time `5m` migration

## Goals

1. Chart ranges read a dedicated bar interval so series are dense (~hundreds of points where Yahoo + RTH allow).
2. Daily sync gap-fills recent bars, then compacts aged fine bars into coarser intervals.
3. Migrate existing `5m` data into the new ladder and stop using `5m`.

## Chart mapping

| UI range | Duration | `bar_interval` |
|----------|----------|----------------|
| 1D | 1 | `1m` |
| 7D | 7 | `15m` |
| 2W | 14 | `30m` |
| 1M | 30 | `1h` |
| 3M / 6M / 1Y / All | 90+ / all | `1d` |

## Retention after compaction

| Interval | Keep |
|----------|------|
| `1m` | last 2 calendar days |
| `15m` | last 8 days |
| `30m` | last 16 days |
| `1h` | last 35 days |
| `1d` | forever |

## Daily sync (per ticker)

1. Gap-fill each band from yfinance (short period when fresh; longer if stale/missing).
2. Compact: for each fine band past its window, ensure coarser OHLCV bars exist, then delete expired fine bars.
3. Upsert on `(ticker, bar_ts, bar_interval)`.

## Migration (once)

Aggregate existing `5m` → `15m` / `30m` / `1h` (+ promote daily closes as needed), keep `1d`, delete all `5m`.

## Non-goals

- Guaranteeing 250–400 points on every equity RTH range (Yahoo + session length limits).
- Intraday bars older than Yahoo’s native lookbacks without paid vendors.
