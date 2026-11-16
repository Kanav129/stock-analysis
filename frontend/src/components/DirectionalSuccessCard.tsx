import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { DirectionalOutcome, DirectionalSuccess } from '../api/types';
import { DeltaValue } from './DeltaValue';
import { RatingBadge } from './RatingBadge';
import { scoreTextClass } from '../lib/reportDepth';

function fmtHitRate(rate: number | null | undefined): string {
  if (rate == null || Number.isNaN(rate)) return '—';
  return `${Math.round(rate * 100)}%`;
}

function rateClass(rate: number | null | undefined): string {
  if (rate == null || Number.isNaN(rate)) return 'text-[var(--color-text-muted)]';
  return rate >= 0.5 ? 'text-[var(--color-up)]' : 'text-[var(--color-down)]';
}

function fmtWeek(iso: string | null | undefined): string {
  if (!iso) return '';
  const [y, m, d] = iso.split('-').map(Number);
  if (!y || !m || !d) return iso;
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
  });
}

function fmtScore(score: number | null): string {
  if (score == null) return '—';
  return score > 0 ? `+${score}` : String(score);
}

const OUTCOME_LABEL: Record<DirectionalOutcome, string> = {
  hit: 'Hit',
  miss: 'Miss',
  unscored: 'Unscored',
};

function outcomeClass(outcome: DirectionalOutcome): string {
  if (outcome === 'hit') return 'text-[var(--color-up)]';
  if (outcome === 'miss') return 'text-[var(--color-down)]';
  return 'text-[var(--color-text-muted)]';
}

function subtitleFor(data: DirectionalSuccess | undefined): string {
  const week = data?.week.week_start ? `Week of ${fmtWeek(data.week.week_start)} · ` : '';
  return `${week}5-day direction`;
}

function weekNote(data: DirectionalSuccess): string | null {
  const week = data.week;
  if (week.status === 'pending_fallback' && week.pending_week_start && week.week_start) {
    return `Week of ${fmtWeek(week.pending_week_start)} does not have 5-day closes yet. Showing the previous complete week (week of ${fmtWeek(week.week_start)}).`;
  }
  if (week.status === 'pending' && week.pending_week_start) {
    return `Week of ${fmtWeek(week.pending_week_start)} does not have 5-day closes yet. No earlier complete week to show.`;
  }
  if (week.status === 'empty') {
    return week.message ?? 'No weekly core ratings yet.';
  }
  return null;
}

function HorizonRate({ label, rate }: { label: string; rate: number | null | undefined }) {
  return (
    <span className="inline-flex items-baseline gap-x-1.5">
      <span className="font-mono text-[length:var(--text-label)] text-[var(--color-text-muted)]">
        {label}
      </span>
      <span
        className={`font-mono text-[length:var(--text-data)] font-semibold tabular-nums ${rateClass(rate)}`}
      >
        {fmtHitRate(rate)}
      </span>
    </span>
  );
}

/** Hit rates on the portfolio row. The breakdown is a floating menu, not a desk tile. */
export function DirectionalSuccessControl({ className = '' }: { className?: string }) {
  const q = useQuery({
    queryKey: ['directional-success'],
    queryFn: () => api.getDirectionalSuccess(),
    staleTime: 60_000,
    retry: 2,
  });
  const [open, setOpen] = useState(false);
  const [ticker, setTicker] = useState('');
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const selectId = useId();
  const titleId = useId();

  const data = q.data;
  const rows = useMemo(() => data?.week.rows ?? [], [data]);
  const tickers = useMemo(
    () => [...new Set(rows.map((row) => row.ticker))].sort(),
    [rows],
  );
  const activeTicker = ticker && tickers.includes(ticker) ? ticker : '';
  const visible = activeTicker ? rows.filter((row) => row.ticker === activeTicker) : rows;
  const note = data ? weekNote(data) : null;
  const failed = q.isError && !data;
  const loading = q.isLoading && !data;

  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setOpen(false);
        triggerRef.current?.focus();
      }
    }
    function onPointer(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPointer);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointer);
    };
  }, [open]);

  return (
    <div ref={rootRef} className={`relative z-10 min-w-0 ${className}`}>
      <button
        ref={triggerRef}
        type="button"
        className="inline-flex max-w-full items-baseline gap-x-3 bg-transparent p-0 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-accent)]"
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-controls={panelId}
        aria-busy={loading || undefined}
        onClick={() => setOpen((value) => !value)}
      >
        {failed ? (
          <span className="font-mono text-[length:var(--text-label)] text-[var(--color-down)]">
            Directional unavailable
          </span>
        ) : (
          <>
            <HorizonRate label="5-day" rate={loading ? null : data?.overall['5d']?.hit_rate} />
            <HorizonRate label="20-day" rate={loading ? null : data?.overall['20d']?.hit_rate} />
          </>
        )}
        <span
          aria-hidden
          className="font-mono text-[length:var(--text-label)] text-[var(--color-text-muted)]"
        >
          ▾
        </span>
        <span className="sr-only">
          {failed
            ? 'Directional experiment unavailable'
            : loading
              ? 'Loading directional experiment'
              : 'Directional experiment'}
        </span>
      </button>

      {open ? (
        <div
          id={panelId}
          role="dialog"
          aria-labelledby={titleId}
          className="desk-overlay absolute right-0 z-30 mt-1.5 w-[min(28rem,calc(100vw-1.5rem))] p-3"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h3
                id={titleId}
                className="font-display text-[length:var(--text-label)] font-semibold uppercase tracking-[0.06em] text-[var(--color-text-secondary)]"
              >
                Directional experiment
              </h3>
              <p className="mt-0.5 text-[length:var(--text-label)] text-[var(--color-text-muted)]">
                {subtitleFor(data)}
              </p>
            </div>
            {tickers.length > 0 ? (
              <label className="relative shrink-0">
                <span className="sr-only" id={selectId}>
                  Filter tickers
                </span>
                <select
                  aria-labelledby={selectId}
                  value={activeTicker}
                  onChange={(event) => setTicker(event.target.value)}
                  className="appearance-none rounded-md border border-[var(--gridline)] bg-[var(--color-surface-2)] py-1 pl-2 pr-6 font-sans text-[length:var(--text-label)] font-semibold text-[var(--color-text-secondary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--color-accent)]"
                >
                  <option value="">All tickers</option>
                  {tickers.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
                <span
                  aria-hidden
                  className="pointer-events-none absolute top-1/2 right-1.5 -translate-y-1/2 font-mono text-[length:var(--text-micro)] text-[var(--color-text-muted)]"
                >
                  ▾
                </span>
              </label>
            ) : null}
          </div>

          {loading ? (
            <p className="mt-2 text-[length:var(--text-label)] text-[var(--color-text-muted)]">
              Loading directional experiment…
            </p>
          ) : null}

          {failed ? (
            <p className="mt-2 text-[length:var(--text-label)] text-[var(--color-down)]">
              {q.error instanceof Error ? q.error.message : 'Failed to load directional experiment.'}
            </p>
          ) : null}

          {note ? (
            <p className="mt-2 text-[length:var(--text-label)] text-[var(--color-text-muted)]">{note}</p>
          ) : null}

          {visible.length > 0 ? (
            <div className="mt-2 flex max-h-72 flex-col overflow-auto">
              <p className="sr-only">Ticker, core rating, score, 5-day return, and hit or miss.</p>
              {visible.map((row) => (
                <Link
                  key={`${row.ticker}-${row.rated_at}`}
                  to={`/stock/${row.ticker}`}
                  onClick={() => setOpen(false)}
                  className="flex min-w-0 items-center gap-2 border-b border-[var(--color-surface-3)] py-1.5 last:border-0 hover:bg-[var(--color-surface-2)]"
                >
                  <span className="w-12 shrink-0 font-mono text-xs font-semibold text-[var(--color-accent)]">
                    {row.ticker}
                  </span>
                  {row.rating ? (
                    <RatingBadge rating={row.rating} reportType="core" />
                  ) : (
                    <span className="text-xs text-[var(--color-text-muted)]">—</span>
                  )}
                  <span className={scoreTextClass('core')}>{fmtScore(row.score)}</span>
                  <DeltaValue
                    value={row.return_5d == null ? null : row.return_5d * 100}
                    className="ml-auto text-[11px]"
                  />
                  <span
                    className={`w-16 shrink-0 text-right text-[11px] ${outcomeClass(row.outcome)}`}
                  >
                    {OUTCOME_LABEL[row.outcome] ?? 'Unscored'}
                  </span>
                </Link>
              ))}
            </div>
          ) : null}

          {data?.disclaimer ? (
            <p className="mt-2 text-[length:var(--text-label)] leading-snug text-[var(--color-text-muted)]">
              {data.disclaimer}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
