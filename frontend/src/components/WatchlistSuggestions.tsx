import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type { WatchlistSuggestion } from '../api/types';
import { LoadingState } from './LoadingSpinner';
import { Panel } from './Panel';

function truncate(text: string, max = 100) {
  const t = text.trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max - 1)}…`;
}

export function WatchlistSuggestions({
  dense = false,
  asPanel = true,
  maxRows,
}: {
  dense?: boolean;
  /** When false, render a plain section (Watchlist page). */
  asPanel?: boolean;
  maxRows?: number;
}) {
  const qc = useQueryClient();
  const suggestionsQ = useQuery({
    queryKey: ['watchlist-suggestions'],
    queryFn: api.getWatchlistSuggestions,
    staleTime: 30_000,
  });

  const accept = useMutation({
    mutationFn: (ticker: string) => api.acceptWatchlistSuggestion(ticker),
    onMutate: async (ticker) => {
      await qc.cancelQueries({ queryKey: ['watchlist-suggestions'] });
      const prev = qc.getQueryData<{ items: WatchlistSuggestion[] }>(['watchlist-suggestions']);
      if (prev) {
        qc.setQueryData(['watchlist-suggestions'], {
          items: prev.items.filter((i) => i.ticker !== ticker),
        });
      }
      return { prev };
    },
    onError: (_e, _t, ctx) => {
      if (ctx?.prev) qc.setQueryData(['watchlist-suggestions'], ctx.prev);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['watchlist-suggestions'] });
      qc.invalidateQueries({ queryKey: ['watchlist'] });
      qc.invalidateQueries({ queryKey: ['desk-snapshot'] });
      qc.invalidateQueries({ queryKey: ['universe'] });
      qc.invalidateQueries({ queryKey: ['jobs'] });
      qc.invalidateQueries({ queryKey: ['analysis-status'] });
    },
  });

  const items = suggestionsQ.data?.items ?? [];
  const visible = maxRows != null ? items.slice(0, maxRows) : items;
  const accepting = accept.isPending ? accept.variables : null;

  const body = suggestionsQ.isLoading ? (
    <LoadingState label="Loading suggestions…" compact={dense} minHeight={dense ? '6rem' : '8rem'} />
  ) : visible.length === 0 ? (
    <p className="text-xs text-[var(--color-text-muted)]">
      No strong ideas right now. Sync again later — some days may have none.
    </p>
  ) : (
    <div className={`flex flex-col ${dense ? '' : 'gap-0'}`}>
      {visible.map((item) => {
        const blurb = item.company_blurb?.trim() || item.company_name?.trim() || '';
        return (
          <div
            key={item.ticker}
            className="flex items-start gap-2 border-b border-[var(--color-surface-3)] py-2 last:border-0"
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline gap-2">
                <Link
                  to={`/suggestions/${item.ticker}`}
                  className="shrink-0 font-mono text-xs font-semibold text-[var(--color-accent)] hover:underline"
                >
                  {item.ticker}
                </Link>
                {item.company_name ? (
                  <span className="truncate text-[11px] text-[var(--color-text-muted)]">
                    {item.company_name}
                  </span>
                ) : null}
              </div>
              {blurb ? (
                <p className="mt-0.5 text-xs leading-snug text-[var(--color-text-primary)]">
                  {truncate(blurb, dense ? 100 : 160)}
                </p>
              ) : null}
              <p className="mt-0.5 text-[11px] leading-snug text-[var(--color-text-secondary)]">
                {truncate(item.reason, dense ? 90 : 140)}
              </p>
            </div>
            <button
              type="button"
              title={`Add ${item.ticker} to watchlist`}
              disabled={accept.isPending}
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                accept.mutate(item.ticker);
              }}
              className="shrink-0 rounded border border-[var(--color-surface-3)] px-1.5 py-0.5 font-mono text-sm leading-none text-[var(--color-accent)] hover:bg-[var(--color-surface-2)] disabled:opacity-40"
            >
              {accepting === item.ticker ? '…' : '+'}
            </button>
          </div>
        );
      })}
    </div>
  );

  if (!asPanel) {
    return (
      <section className="rounded-lg bg-[var(--color-surface-1)]">
        <header className="border-b border-[var(--color-surface-3)] px-4 py-3">
          <h3 className="font-display text-sm font-semibold text-[var(--color-text-primary)]">
            Suggested for watchlist
          </h3>
          <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">
            Strong ideas only · tap ticker for the full brief · expires in 7 days
          </p>
        </header>
        <div className="px-4 py-3">{body}</div>
      </section>
    );
  }

  return (
    <Panel title="Suggested for watchlist" subtitle="Strong ideas · tap ticker for brief" dense={dense}>
      {body}
    </Panel>
  );
}
