# Cancel running sync (soft / resumable)

**Date:** 2026-07-26  
**Status:** Approved  

## Goal

Stop an in-flight price/news sync without discarding completed tickers for the HKT day.

## Behavior

- `POST /sync/cancel` sets `cancel_requested`.
- Worker stops between tickers / stages (current ticker may finish).
- Checkpoint saved as `cancelled` with existing `news_done` / `prices_done` intact → next Sync resumes.
- UI: Cancel on Sync progress panel (mirror analysis).

## Analysis

Already has `POST /analysis/cancel` + Cancel button — no change required.
