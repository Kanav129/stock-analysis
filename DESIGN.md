---
name: Stock Analysis — Personal Desk
description: Private trading desk UI — sync → report → rating, dense and instrumental
colors:
  # Near-neutral dark elevations (clearer steps, less muddy blue cast) + vivid system accent.
  desk-azure: "oklch(0.70 0.19 250)"
  desk-azure-hover: "oklch(0.78 0.17 250)"
  surface-0: "oklch(0.11 0.006 255)"
  surface-1: "oklch(0.17 0.010 255)"
  surface-2: "oklch(0.23 0.012 255)"
  surface-3: "oklch(0.30 0.014 255)"
  text-primary: "oklch(0.97 0.004 255)"
  text-secondary: "oklch(0.80 0.014 255)"
  text-muted: "oklch(0.64 0.012 255)"
  up: "oklch(0.78 0.16 155)"
  down: "oklch(0.68 0.19 25)"
  hold: "oklch(0.82 0.12 90)"
  rating-strong-buy: "oklch(0.80 0.18 145)"
  rating-buy: "oklch(0.76 0.16 155)"
  rating-accumulate: "oklch(0.78 0.13 130)"
  rating-hold: "oklch(0.82 0.13 95)"
  rating-reduce: "oklch(0.76 0.16 55)"
  rating-sell: "oklch(0.70 0.18 35)"
  rating-strong-sell: "oklch(0.64 0.20 22)"
typography:
  # Tracking is size-specific: positive on small uppercase labels, near 0 on body/data,
  # slight negative (~-0.02em) on large display titles so letters don't read too open.
  badge:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    fontSize: "0.5625rem"
    fontWeight: 600
    letterSpacing: "0.04em"
  micro:
    fontFamily: "Hanken Grotesk, system-ui, sans-serif"
    fontSize: "0.625rem"
    fontWeight: 600
    letterSpacing: "0.06em"
  display:
    fontFamily: "Schibsted Grotesk Variable, system-ui, sans-serif"
    fontSize: "0.6875rem"
    fontWeight: 700
    letterSpacing: "0.08em"
  label:
    fontFamily: "Hanken Grotesk, system-ui, sans-serif"
    fontSize: "0.6875rem"
    fontWeight: 600
    letterSpacing: "0.08em"
  ui:
    fontFamily: "Hanken Grotesk, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 600
  data:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    fontSize: "0.8125rem"
    fontWeight: 500
  body:
    fontFamily: "Hanken Grotesk, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.45
  title-sm:
    fontFamily: "Schibsted Grotesk Variable, system-ui, sans-serif"
    fontSize: "1.05rem"
    fontWeight: 600
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Schibsted Grotesk Variable, system-ui, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.02em"
  metric:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    fontSize: "1.25rem"
    fontWeight: 600
    letterSpacing: "-0.02em"
  stat:
    fontFamily: "Schibsted Grotesk Variable, system-ui, sans-serif"
    fontSize: "1.35rem"
    fontWeight: 600
    letterSpacing: "-0.02em"
rounded:
  sm: "4px"
  md: "6px"
  nested: "10px"
  surface: "12px"
  chrome: "18px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  2xl: "32px"
  3xl: "48px"
components:
  button-terminal:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.sm}"
    padding: "5px 10px"
  button-terminal-hover:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.text-primary}"
  button-desk-run:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.pill}"
    padding: "8px 16px"
    height: "40px"
  button-desk-run-accent:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.desk-azure}"
    rounded: "{rounded.pill}"
    padding: "8px 16px"
  panel:
    backgroundColor: "{colors.surface-1}"
    rounded: "{rounded.md}"
    padding: "12px 16px"
---

# Design System: Stock Analysis — Personal Desk

## 1. Overview

**Creative North Star: "The Decision Console"**

This is a private night-side trading desk: cool-blue darkness, dense panels, and controls that behave like instruments. The interface exists to finish a decision loop — sync data, run analysis, read the call — with operational honesty about progress, cancel, and resume. Personality is sharp, dense, terminal, and no-nonsense: status and numbers first, celebration never.

Depth comes from stacked surfaces and hairline gridlines more than glow. Accent (Desk Azure) is scarce — selection, active ranges, and primary pipeline actions. Market semantics (up / down / hold / rating ladder) carry meaning; decoration does not.

The system explicitly rejects generic SaaS analytics dashboards — purple gradients, identical card grids, and fluffy “insights” marketing chrome that dilute a trading desk.

**Key Characteristics:**
- Cool-blue dark tonal surfaces (`surface-0` → `surface-3`)
- Restrained Desk Azure accent (≤10% of any screen)
- Display + humanist body + mono data trio
- Dense 12-column terminal grid, 6px panel corners
- Soft elevation reserved for floating overlays (tooltips)
- Motion only for state: 150–280ms ease-out-expo, reduced-motion respected

## 2. Colors

Modern dark desk: near-neutral elevations with clear luminance steps (not muddy blue-gray sludge), vibrant secondary labels, one vivid system accent, and a full semantic rating ladder.

### Primary
- **Desk Azure** (`oklch(0.70 0.19 250)` / `--color-accent`): Active chart ranges, accent terminal buttons, Sync/Analysis emphasis borders, ticker links, focus rings. Hover lifts to `oklch(0.78 0.17 250)`.

### Neutral
- **Void Pit** (`oklch(0.11 0.006 255)` / `--color-surface-0`): App chrome / page ground — deep, nearly neutral.
- **Console Deck** (`oklch(0.17 0.010 255)` / `--color-surface-1`): Panel fills, floating header glass base.
- **Well Plate** (`oklch(0.23 0.012 255)` / `--color-surface-2`): Controls, segmented tracks, nested wells.
- **Rail Edge** (`oklch(0.30 0.014 255)` / `--color-surface-3`): Stronger fills, pressed nav, borders — visibly stepped from surface-2.
- **Signal Ink** (`oklch(0.97 0.004 255)`): Primary text / prices — bright for vibrancy over glass.
- **Secondary Ink** (`oklch(0.80 0.014 255)`): Supporting labels (alive, not washed gray).
- **Muted Ink** (`oklch(0.64 0.012 255)`): Panel titles, quiet meta (keep ≥ readable for labels; never for body paragraphs).
- **Gridline**: `color-mix` of surface-3 at ~80% — hairline dividers only.

### Semantic (market & ratings)
- **Tape Green / Up** (`oklch(0.78 0.16 155)`): Positive deltas, Done badges.
- **Tape Red / Down** (`oklch(0.68 0.19 25)`): Negative deltas, errors.
- **Hold Amber** (`oklch(0.82 0.12 90)`): Neutral / resume cues.
- **Rating ladder** (strong-buy → strong-sell): seven distinct OKLCH steps for badges — never collapse to two colors.

### Named Rules
**The One Signal Rule.** Desk Azure appears on ≤10% of any screen. If everything is accented, nothing is.

**The Ladder Rule.** Rating meaning uses the named ladder tokens; never invent a one-off green/red for ratings.

## 3. Typography

**Display Font:** Schibsted Grotesk Variable (with system-ui)
**Body Font:** Hanken Grotesk (with system-ui)
**Label/Mono Font:** JetBrains Mono (with ui-monospace)

**Character:** Schibsted carries desk titles and panel kicker labels (uppercase, tracked). Hanken is the workhorse UI. JetBrains owns prices, tickers, percentages, and technicals — tabular nums always on.

### Hierarchy
- **Display / Panel kicker** (700, `0.6875rem`, tracking `0.08em`, uppercase): Panel titles — quiet chrome, not hero shout.
- **Title** (600, ~`1.125rem`): Page titles (“Trading Desk”).
- **Body** (400, ~`0.875rem`, line-height ~1.45): Secondary copy, empty states; keep prose ≤75ch when present.
- **Label** (600, `0.6875rem`): Meta, badges companion text.
- **Data** (500, `0.8125rem`, mono): Quotes, P&L, technicals grid, chart axes.

### Named Rules
**The Mono Means Money Rule.** Numeric market data is always JetBrains Mono with tabular figures. Body sans never carries live prices.

**The No Hero Clamp Rule.** Product type uses fixed rem steps — no fluid marketing `clamp()` headlines on the desk.

## 4. Elevation

Depth is mostly tonal: surface-0 ground, surface-1 panels, surface-2 controls, 1px gridline borders. Cards are not the default container — panels are.

Soft shadows are rare and reserved for floating UI (e.g. chart tooltips: `0 8px 24px` mixed from surface-0). Sticky header may use a light backdrop blur for readability while scrolling; that is chrome, not card glassmorphism.

### Shadow Vocabulary
- **Overlay lift** (`box-shadow: 0 8px 24px color-mix(in oklch, var(--color-surface-0) 55%, transparent)`): Tooltips / ephemeral overlays only.

### Named Rules
**The Flat-By-Default Rule.** Surfaces at rest cast no shadow. If a panel needs presence, step its surface token or border — don’t invent a drop shadow.

## 5. Components

Dense and instrumental: small radii on data chrome, full pills only for primary pipeline CTAs.

### Buttons
- **Terminal** (secondary ops): 4px radius, surface-2 fill, 1px surface-3 border, 5×10 padding, 12px semibold. Hover: primary ink + Desk Azure border.
- **Terminal accent**: Desk Azure text/border mix — Cancel, Manage, secondary pipeline.
- **Desk-run pills** (Sync / Analysis): full pill (`999px`), min-height 40px, 8×16 padding, optional mono Done/Resume badges. Accent / done / resume variants tint the border via semantic mixes.
- **Hover / Focus:** 160ms ease-out-expo on color/border; focus-visible uses Desk Azure outline on segmented controls.
- **Disabled:** opacity ~0.5–0.55, not-allowed cursor.

### Chips
- Rating badges use the ladder tokens; compact, high-contrast text on tinted fills.
- Chart-range segment: surface-2 track, mono 11px buttons; pressed state = Desk Azure fill on surface-0 ink.

### Cards / Containers
- **Terminal panel:** surface-1, 6px radius, 1px gridline border. Header with uppercase muted title; dense body padding 8–10px when `dense`.
- **No nested cards.** Wells use surface-2 / surface-0, not a second panel chrome.
- **Internal padding:** sm/md scale (8–16px).

### Inputs / Fields
- Match terminal control language: surface-2 wells, surface-3 borders, 4–6px radius. Focus: Desk Azure border (no neon glow stacks).

### Navigation
- Sticky header on surface-1 (~95% + light blur). Nav links: 12px semibold; active = surface-3 chip; idle = secondary ink → primary on hover.
- Brand lockup stays quiet (small tracked “Personal Desk” + “Stock Analysis”) — not a marketing hero.

### Signature: Desk-run actions
Pill Sync / Analysis row aligned to the page header; badges communicate Done · time / Resume · n/total without a second status row.

### Signature: Price chart
Area stroke Desk Azure, muted grid, ET-aware ticks on intraday ranges; delta line uses up/down tokens.

## 6. Do's and Don'ts

### Do:
- **Do** keep Desk Azure scarce — selection, focus, and primary pipeline emphasis only.
- **Do** use the rating ladder tokens for every rating surface.
- **Do** put prices, tickers, and % in JetBrains Mono with tabular nums.
- **Do** prefer tonal surface steps + gridlines over shadows for panel hierarchy.
- **Do** skeleton in place for loading; never block the whole desk behind one spinner.
- **Do** honor `prefers-reduced-motion` (crossfade or instant; no stuck opacity:0 reveals).
- **Do** keep Sync/Analysis as pill instruments with honest Done/Resume state.

### Don't:
- **Don't** ship generic SaaS analytics dashboards — purple gradients, identical card grids, and fluffy “insights” marketing chrome that dilute a trading desk. (PRODUCT.md anti-reference, verbatim.)
- **Don't** use side-stripe borders (`border-left` / `border-right` > 1px) as accent decoration.
- **Don't** use gradient text or decorative glassmorphism on panels.
- **Don't** invent hero-metric SaaS layouts (giant number + fluff stats strip) for the desk header.
- **Don't** put display type in buttons or table cells — Schibsted is for titles/kickers only.
- **Don't** animate width/height for progress; use transform/opacity (or the existing scaleX progress fills).
- **Don't** treat every section as a card; panels and wells are the container vocabulary.
