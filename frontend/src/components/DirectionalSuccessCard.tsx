import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { DirectionalOutcome, DirectionalSuccess } from '../api/types';
import { DeltaValue } from './DeltaValue';
import { Panel } from './Panel';
import { RatingBadge } from './RatingBadge';
import { scoreTextClass } from '../lib/reportDepth';

function fmtHitRate(rate: number | null | undefined): string {
  if (rate == null || Number.isNaN(rate)) return '—';
  return `${Math.round(rate * 100)}%`;
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
  return `${week}Weekly core calls · 5-day direction. Not a performance promise.`;
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

export function DirectionalSuccessCard() {
  const q = useQuery({
    queryKey: ['directional-success'],
    queryFn: () => api.getDirectionalSuccess(),
    staleTime: 60_000,
    retry: 2,
  });

  const data = q.data;
  const five = data?.overall['5d'];
  const twenty = data?.overall['20d'];
  const rows = data?.week.rows ?? [];
  const note = data ? weekNote(data) : null;

  return (
    <Panel title="Directional experiment" subtitle={subtitleFor(data)} dense>
      {q.isLoading && !data ? (
        <p className="text-xs text-[var(--color-text-muted)]">Loading directional experiment…</p>
      ) : q.isError && !data ? (
        <p className="text-xs text-[var(--color-down)]">
          {q.error instanceof Error ? q.error.message : 'Failed to load directional experiment.'}
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <p className="font-mono text-lg font-semibold tabular-nums text-[var(--color-text-primary)]">
              {fmtHitRate(five?.hit_rate)}
              <span className="ml-2 font-sans text-xs font-normal text-[var(--color-text-muted)]">
                5-day · n={five?.n ?? 0}
              </span>
            </p>
            <p className="font-mono text-xs tabular-nums text-[var(--color-text-secondary)]">
              20-day {fmtHitRate(twenty?.hit_rate)}
              <span className="text-[var(--color-text-muted)]"> · n={twenty?.n ?? 0}</span>
            </p>
          </div>

          {note ? (
            <p className="text-xs text-[var(--color-text-secondary)]">{note}</p>
          ) : null}

          {rows.length === 0 ? null : (
            <div className="flex max-h-72 flex-col overflow-auto">
              <p className="sr-only">Ticker, core rating, score, 5-day return, and hit or miss.</p>
              {rows.map((row) => (
                <Link
                  key={`${row.ticker}-${row.rated_at}`}
                  to={`/stock/${row.ticker}`}
                  className="flex min-w-0 items-center gap-2 border-b border-[var(--color-surface-3)] py-1 last:border-0 hover:bg-[var(--color-surface-2)]"
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
          )}
        </div>
      )}
    </Panel>
  );
}
