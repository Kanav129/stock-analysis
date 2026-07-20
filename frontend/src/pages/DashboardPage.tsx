import { Link } from 'react-router-dom';
import { useEffect, useMemo, useRef } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { PortfolioSummaryCard } from '../components/PortfolioSummary';
import { HoldingsTable } from '../components/HoldingsTable';
import { RunAnalysisButton } from '../components/RunAnalysisButton';
import { SyncDataButton } from '../components/SyncDataButton';
import { SyncProgressTracker } from '../components/SyncProgressTracker';
import { AnalysisProgressTracker } from '../components/AnalysisProgressTracker';
import { Panel } from '../components/Panel';
import { HeatTile } from '../components/HeatTile';
import { DeltaValue } from '../components/DeltaValue';
import { Sparkline } from '../components/Sparkline';
import { RatingBadge } from '../components/RatingBadge';
import { Skeleton } from '../components/Skeleton';
import type { Rating, SyncProgress } from '../api/types';

const MARKET_TICKERS = ['SPY', 'QQQ', 'IWM', 'DIA'];

/** Keep last successful payload visible while a slow refetch waits on the API. */
function keepPrevious<T>(previousData: T | undefined) {
  return previousData;
}

export function DashboardPage() {
  const qc = useQueryClient();

  // Lightweight — in-memory on the API; safe to poll even during sync
  const syncQ = useQuery({
    queryKey: ['sync-status'],
    queryFn: api.getSyncStatus,
    refetchInterval: (q) => {
      const d = q.state.data as SyncProgress | undefined;
      return d?.running || d?.status === 'running' ? 1500 : 30_000;
    },
    staleTime: 1_000,
  });
  const syncing = Boolean(syncQ.data?.running) || syncQ.data?.status === 'running';

  // Critical path — paint desk shell immediately; sections skeleton independently.
  // During sync, pause heavy quote refetches so we don't pile onto a busy DB.
  const holdingsQ = useQuery({
    queryKey: ['holdings'],
    queryFn: api.getHoldings,
    refetchInterval: syncing ? false : 60_000,
    staleTime: 30_000,
    placeholderData: keepPrevious,
  });
  const ratingsQ = useQuery({
    queryKey: ['ratings'],
    queryFn: api.getRatings,
    refetchInterval: syncing ? false : 60_000,
    staleTime: 30_000,
    placeholderData: keepPrevious,
  });
  const watchlistQ = useQuery({
    queryKey: ['watchlist'],
    queryFn: api.getWatchlist,
    staleTime: 60_000,
    placeholderData: keepPrevious,
  });

  const analysisQ = useQuery({
    queryKey: ['analysis-status'],
    queryFn: api.getAnalysisStatus,
    refetchInterval: (q) => (q.state.data?.running ? 800 : 30_000),
    staleTime: 5_000,
  });

  const wasRunning = useRef(false);
  useEffect(() => {
    const running = !!analysisQ.data?.running;
    if (wasRunning.current && !running) {
      qc.invalidateQueries({ queryKey: ['ratings'] });
      qc.invalidateQueries({ queryKey: ['watchlist'] });
      qc.invalidateQueries({ queryKey: ['report'] });
    }
    wasRunning.current = running;
  }, [analysisQ.data?.running, qc]);

  const quoteTickers = useMemo(() => {
    const fromHoldings = (holdingsQ.data?.holdings ?? []).map((h) => h.ticker);
    const fromWatch = (watchlistQ.data?.items ?? []).map((i) => i.ticker);
    return [...new Set([...MARKET_TICKERS, ...fromHoldings, ...fromWatch])];
  }, [holdingsQ.data, watchlistQ.data]);

  const marketQuotesQ = useQuery({
    queryKey: ['quotes', 'market', MARKET_TICKERS.join(',')],
    queryFn: () => api.getQuotes(MARKET_TICKERS, 30),
    staleTime: 30_000,
    refetchInterval: syncing ? false : 60_000,
    placeholderData: keepPrevious,
  });

  const deskQuotesQ = useQuery({
    queryKey: ['quotes', 'desk', quoteTickers.join(',')],
    queryFn: () => api.getQuotes(quoteTickers, 30),
    enabled: quoteTickers.length > MARKET_TICKERS.length,
    staleTime: 30_000,
    refetchInterval: syncing ? false : 60_000,
    placeholderData: keepPrevious,
  });

  const quotes = useMemo(
    () => ({
      ...(marketQuotesQ.data?.quotes ?? {}),
      ...(deskQuotesQ.data?.quotes ?? {}),
    }),
    [marketQuotesQ.data, deskQuotesQ.data],
  );

  const summary = holdingsQ.data?.summary ?? {
    total_value: 0,
    total_unrealized_pnl: 0,
    position_count: 0,
    snapshot_at: null,
  };

  const ratings = ratingsQ.data?.ratings ?? [];
  const ratingMap = Object.fromEntries(ratings.map((r) => [r.ticker, r]));
  const holdingsTickers = (holdingsQ.data?.holdings ?? []).map((h) => h.ticker);

  const heatTickers = useMemo(() => {
    const wl = (watchlistQ.data?.items ?? []).map((i) => i.ticker);
    return [...new Set([...holdingsTickers, ...wl])].slice(0, 24);
  }, [watchlistQ.data, holdingsTickers]);

  const holdingsPending = holdingsQ.isLoading && !holdingsQ.data;
  const ratingsPending = ratingsQ.isLoading && !ratingsQ.data;

  return (
    <div className="flex flex-col gap-3 animate-fade-up">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="font-display text-lg font-semibold">Trading Desk</h2>
          <p className="mt-0.5 text-xs text-[var(--color-text-secondary)]">
            {analysisQ.data?.last_run
              ? `Last analysis ${new Date(analysisQ.data.last_run).toLocaleString()}`
              : analysisQ.isLoading
                ? 'Checking last analysis…'
                : 'No analysis run yet'}
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <SyncDataButton />
          <RunAnalysisButton />
        </div>
      </div>

      <SyncProgressTracker />
      <AnalysisProgressTracker />

      <Panel title="Market overview" dense>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {MARKET_TICKERS.map((t) => {
            const q = quotes[t];
            if (marketQuotesQ.isLoading && !q) {
              return <Skeleton key={t} className="h-[58px] w-full rounded" />;
            }
            return (
              <Link
                key={t}
                to={`/stock/${t}`}
                className="rounded border border-[var(--color-surface-3)] px-2.5 py-2 transition-colors hover:border-[var(--color-accent)]"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs font-semibold">{t}</span>
                  <Sparkline data={q?.spark ?? []} width={48} height={16} />
                </div>
                <div className="mt-1 flex items-baseline justify-between gap-2">
                  <span className="font-mono text-sm">
                    {q?.latest_close != null ? `$${q.latest_close.toFixed(2)}` : '—'}
                  </span>
                  <DeltaValue value={q?.change_pct} className="text-xs" />
                </div>
              </Link>
            );
          })}
        </div>
      </Panel>

      {holdingsPending ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full rounded" />
          ))}
        </div>
      ) : (
        <PortfolioSummaryCard
          summary={summary}
          quotes={quotes}
          holdingsTickers={holdingsTickers}
        />
      )}

      <div className="terminal-grid">
        <div className="col-span-12 lg:col-span-8">
          <Panel title="Holdings" subtitle={`${holdingsTickers.length} positions · prices from latest sync`}>
            {holdingsPending ? (
              <div className="flex flex-col gap-2">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-8 w-full" />
                ))}
              </div>
            ) : (
              <HoldingsTable
                holdings={holdingsQ.data?.holdings ?? []}
                ratings={ratings}
                quotes={quotes}
              />
            )}
          </Panel>
        </div>

        <div className="col-span-12 flex flex-col gap-3 lg:col-span-4">
          <Panel
            title="Universe heatmap"
            actions={
              <Link to="/watchlist" className="btn-terminal">
                Manage
              </Link>
            }
            dense
          >
            {watchlistQ.isLoading && heatTickers.length === 0 ? (
              <div className="grid grid-cols-2 gap-1.5">
                {Array.from({ length: 6 }).map((_, i) => (
                  <Skeleton key={i} className="h-14 w-full rounded" />
                ))}
              </div>
            ) : heatTickers.length === 0 ? (
              <p className="text-xs text-[var(--color-text-muted)]">
                Add watchlist tickers to populate the heatmap.
              </p>
            ) : (
              <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 lg:grid-cols-2">
                {heatTickers.map((t) => (
                  <HeatTile
                    key={t}
                    ticker={t}
                    price={quotes[t]?.latest_close}
                    changePct={quotes[t]?.change_pct}
                    rating={(ratingMap[t]?.rating as Rating | undefined) ?? null}
                  />
                ))}
              </div>
            )}
          </Panel>

          <Panel title="Latest ratings" dense>
            <div className="flex max-h-[280px] flex-col gap-0 overflow-auto">
              {ratingsPending ? (
                Array.from({ length: 6 }).map((_, i) => (
                  <Skeleton key={i} className="mb-1.5 h-7 w-full" />
                ))
              ) : (
                <>
                  {ratings.slice(0, 12).map((r) => (
                    <Link
                      key={r.ticker}
                      to={`/stock/${r.ticker}`}
                      className="flex items-center justify-between gap-2 border-b border-[var(--color-surface-3)] py-1.5 last:border-0 hover:bg-[var(--color-surface-2)]"
                    >
                      <div className="flex min-w-0 items-center gap-2">
                        <span className="font-mono text-xs font-semibold text-[var(--color-accent)]">
                          {r.ticker}
                        </span>
                        <RatingBadge rating={r.rating} />
                      </div>
                      <span
                        className="font-mono text-[11px] tabular-nums"
                        style={{
                          color:
                            (r.score ?? 0) > 15
                              ? 'var(--color-rating-buy)'
                              : (r.score ?? 0) < -15
                                ? 'var(--color-rating-sell)'
                                : 'var(--color-rating-hold)',
                        }}
                      >
                        {(r.score ?? 0) > 0 ? `+${r.score}` : r.score}
                      </span>
                    </Link>
                  ))}
                  {!ratings.length && (
                    <p className="text-xs text-[var(--color-text-muted)]">
                      Run analysis to populate ratings.
                    </p>
                  )}
                </>
              )}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
