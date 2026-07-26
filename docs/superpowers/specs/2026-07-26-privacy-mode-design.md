# Privacy mode (hide portfolio values)

**Date:** 2026-07-26  
**Status:** Approved  
**Scope:** Frontend desk — mask personal money amounts while presenting publicly

## Problem

When showing the desk in public or to others, portfolio totals, per-holding values, P&L $, and quantities reveal personal wealth. Public share prices and % moves are fine to leave visible.

## Goals

1. One eye-icon toggle in the header to hide/show sensitive values.
2. Persist preference in `localStorage` for this browser.
3. Keep public prices and percentage changes visible.

## Non-goals

- Server-side redaction (values may still exist in network JSON).
- Hiding public market prices or % changes.
- Per-panel toggles.

## Decisions

| Topic | Choice |
|-------|--------|
| What to hide | Portfolio total, unrealized P&L $, qty, holding market value, holding P&L $ |
| What to keep | Tickers, share prices, % changes, sparklines, ratings/scores, position count |
| Persistence | `localStorage` key `desk_privacy_mode` |
| Approach | React context + header eye button |
| Mask | Fixed `••••` placeholder (no digit length leak); no P&L color when masked |

## Architecture

- `PrivacyModeProvider` / `usePrivacyMode()` — boolean + toggle, hydrated from localStorage
- Eye control in `Layout` header (`aria-pressed`, “Hide values” / “Show values”)
- `SensitiveValue` — renders mask or children based on privacy flag
- Wire `PortfolioSummaryCard` and `HoldingsTable`

## Testing

Manual: toggle eye → values mask; refresh → state persists; toggle off → values return; % and prices still show when masked.
