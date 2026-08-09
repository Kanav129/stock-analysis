import { Link } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { WatchlistItem } from '../api/types';
import { api } from '../api/client';
import { AnalysisErrorIcon } from './AnalysisErrorIcon';
import { RatingBadge } from './RatingBadge';
import { ScoreMeter } from './ScoreMeter';

function fmtPrice(n: number | null | undefined) {
  if (n == null) return '—';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(n);
}

export function WatchlistList({ items }: { items: WatchlistItem[] }) {
  const qc = useQueryClient();

  const remove = useMutation({
    mutationFn: (ticker: string) => api.removeWatchlist(ticker),
    onMutate: async (ticker) => {
      await qc.cancelQueries({ queryKey: ['watchlist'] });
      const prev = qc.getQueryData<{ items: WatchlistItem[] }>(['watchlist']);
      if (prev) {
        qc.setQueryData(['watchlist'], {
          items: prev.items.filter((i) => i.ticker !== ticker),
        });
      }
      return { prev };
    },
    onError: (_e, _t, ctx) => {
      if (ctx?.prev) qc.setQueryData(['watchlist'], ctx.prev);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['watchlist'] });
      qc.invalidateQueries({ queryKey: ['desk-snapshot'] });
    },
  });

  if (!items.length) {
    return null;
  }

  return (
    <ul className="divide-y divide-[var(--color-surface-3)]">
      {items.map((item) => (
        <li
          key={item.ticker}
          className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-start sm:gap-6"
        >
          <div className="flex min-w-[5rem] shrink-0 flex-col gap-1">
            <Link
              to={`/stock/${item.ticker}`}
              className="font-mono text-base font-medium text-[var(--color-accent)] hover:underline"
            >
              {item.ticker}
            </Link>
            <span className="font-mono text-sm text-[var(--color-text-primary)]">
              {fmtPrice(item.latest_price)}
            </span>
            {item.price_date && (
              <span className="text-xs text-[var(--color-text-muted)]">
                {new Date(item.price_date).toLocaleDateString()}
              </span>
            )}
          </div>

          <div className="flex shrink-0 flex-col gap-2 sm:pt-0.5">
            {item.rating || item.analysis_failed ? (
              <div className="flex flex-wrap items-center gap-3">
                {item.rating ? (
                  <RatingBadge rating={item.rating} reportType={item.report_type} />
                ) : null}
                <AnalysisErrorIcon
                  analysisFailed={item.analysis_failed}
                  analysisError={item.analysis_error}
                  failedAt={item.failed_at}
                />
                {item.score != null && (
                  <ScoreMeter value={item.score} reportType={item.report_type} />
                )}
              </div>
            ) : (
              <span className="text-sm text-[var(--color-text-muted)]">No rating</span>
            )}
          </div>

          <p className="min-w-0 flex-1 text-sm leading-relaxed text-[var(--color-text-secondary)]">
            {item.description ?? 'No description yet. Run sync and analysis to populate insights.'}
          </p>

          <button
            type="button"
            onClick={() => remove.mutate(item.ticker)}
            disabled={remove.isPending}
            className="shrink-0 self-start text-sm text-[var(--color-text-muted)] hover:text-[var(--color-down)] disabled:opacity-50"
          >
            Remove
          </button>
        </li>
      ))}
    </ul>
  );
}
