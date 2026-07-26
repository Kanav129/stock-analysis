import { Link } from 'react-router-dom';
import { useEffect, useMemo, useRef } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { PortfolioSummaryCard } from '../components/PortfolioSummary';
import { HoldingsTable } from '../components/HoldingsTable';
import { DeskRunActions } from '../components/DeskRunActions';
import { SyncProgressTracker } from '../components/SyncProgressTracker';
import { AnalysisProgressTracker } from '../components/AnalysisProgressTracker';
import { Panel } from '../components/Panel';
import { HeatTile } from '../components/HeatTile';
import { DeltaValue } from '../components/DeltaValue';
import { Sparkline } from '../components/Sparkline';
import { Skeleton } from '../components/Skeleton';
import { RatingBadge } from '../components/RatingBadge';
import type { Rating, SyncProgress, StockQuote } from '../api/types';
import { useLivePriceRefresh } from '../hooks/useLivePriceRefresh';
import { isUsRegularSession } from '../lib/usMarketHours';
import { patchDeskCache, readDeskCache } from '../lib/deskCache';

const MARKET_TICKERS = ['SPY', 'QQQ', 'IWM', 'DIA'];
/** Heatmap prefers watchlist; holdings fill remaining slots up to this cap. */
const HEATMAP_CAP = 18;
const CALLS_CAP = 6;

/** Higher = more urgent for the review queue (soft ACCUMULATE ranks below REDUCE/BUY). */
const CALL_PRIORITY: Record<Rating, number> = {
  STRONG_SELL: 4,
  SELL: 4,
  STRONG_BUY: 4,
  BUY: 3,
  REDUCE: 3,
  ACCUMULATE: 1,
  HOLD: 0,
};

const DESK_STALE_MS = 60_000;
const sessionCache = typeof sessionStorage !== 'undefined' ? readDeskCache() : null;

/** Keep last successful payload visible while a slow refetch waits on the API. */
function keepPrevious<T>(previousData: T | undefined) {
  return previousData;
}

function fmtDeskTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

function fmtLiveAt(ms: number | null, liveEnabled: boolean): string {
  if (ms != null) return new Date(ms).toLocaleTimeString();
  if (liveEnabled && isUsRegularSession()) return 'waiting';
  return 'off';
}

export function DashboardPage() {
  const qc = useQueryClient();

  // Lightweight — in-memory on the API; safe to poll even during sync
  const syncQ = useQuery({
    queryKey: ['sync-status'],
    queryFn: api.getSyncStatus,
    refetchInterval: (q) => {
      const d = q.state.data as SyncProgress | undefined;
      return d?.running || d?.status === 'running' ? 500 : 30_000;
    },
    refetchIntervalInBackground: true,
    staleTime: 1_000,
  });
  const syncing = Boolean(syncQ.data?.running) || syncQ.data?.status === 'running';

  // Critical path — paint from session cache immediately, then refresh in background.
  const holdingsQ = useQuery({
    queryKey: ['holdings'],
    queryFn: api.getHoldings,
    refetchInterval: syncing ? false : DESK_STALE_MS,
    staleTime: DESK_STALE_MS,
    placeholderData: keepPrevious,
    initialData: sessionCache?.holdings as Awaited<ReturnType<typeof api.getHoldings>> | undefined,
    initialDataUpdatedAt: sessionCache?.holdings ? sessionCache.at : undefined,
  });
  const ratingsQ = useQuery({
    queryKey: ['ratings'],
    queryFn: api.getRatings,
    refetchInterval: syncing ? false : DESK_STALE_MS,
    staleTime: DESK_STALE_MS,
    placeholderData: keepPrevious,
    initialData: sessionCache?.ratings as Awaited<ReturnType<typeof api.getRatings>> | undefined,
    initialDataUpdatedAt: sessionCache?.ratings ? sessionCache.at : undefined,
  });
  const watchlistQ = useQuery({
    queryKey: ['watchlist'],
    queryFn: api.getWatchlist,
    staleTime: DESK_STALE_MS,
    placeholderData: keepPrevious,
    initialData: sessionCache?.watchlist as Awaited<ReturnType<typeof api.getWatchlist>> | undefined,
    initialDataUpdatedAt: sessionCache?.watchlist ? sessionCache.at : undefined,
  });

  const analysisQ = useQuery({
    queryKey: ['analysis-status'],
    queryFn: api.getAnalysisStatus,
    refetchInterval: (q) => (q.state.data?.running ? 800 : 30_000),
    refetchIntervalInBackground: true,
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

  useEffect(() => {
    if (holdingsQ.data) patchDeskCache({ holdings: holdingsQ.data });
  }, [holdingsQ.data]);
  useEffect(() => {
    if (ratingsQ.data) patchDeskCache({ ratings: ratingsQ.data });
  }, [ratingsQ.data]);
  useEffect(() => {
    if (watchlistQ.data) patchDeskCache({ watchlist: watchlistQ.data });
  }, [watchlistQ.data]);

  const deskOnlyTickers = useMemo(() => {
    const fromHoldings = (holdingsQ.data?.holdings ?? []).map((h) => h.ticker);
    const fromWatch = (watchlistQ.data?.items ?? []).map((i) => i.ticker);
    const market = new Set(MARKET_TICKERS);
    return [...new Set([...fromHoldings, ...fromWatch].map((t) => t.toUpperCase()))].filter(
      (t) => !market.has(t),
    );
  }, [holdingsQ.data, watchlistQ.data]);

  const liveTickers = useMemo(
    () => [...MARKET_TICKERS, ...deskOnlyTickers],
    [deskOnlyTickers],
  );

  // Don't compete with first paint / cold API — Yahoo backfill after desk settles.
  const deskReady = Boolean(holdingsQ.data || watchlistQ.data);
  const liveEnabled = !syncing && deskReady;
  const { lastLiveAt } = useLivePriceRefresh(liveTickers, {
    enabled: liveEnabled,
    deferMs: 45_000,
  });

  const marketQuotesQ = useQuery({
    queryKey: ['quotes', 'market', MARKET_TICKERS.join(',')],
    queryFn: () => api.getQuotes(MARKET_TICKERS, 30),
    staleTime: DESK_STALE_MS,
    refetchInterval: syncing ? false : DESK_STALE_MS,
    placeholderData: keepPrevious,
    initialData: sessionCache?.marketQuotes as
      | { quotes: Record<string, StockQuote> }
      | undefined,
    initialDataUpdatedAt: sessionCache?.marketQuotes ? sessionCache.at : undefined,
  });

  const deskQuoteKey = deskOnlyTickers.join(',');
  const deskQuotesQ = useQuery({
    queryKey: ['quotes', 'desk', deskQuoteKey],
    queryFn: () => api.getQuotes(deskOnlyTickers, 30),
    enabled: deskOnlyTickers.length > 0,
    staleTime: DESK_STALE_MS,
    refetchInterval: syncing ? false : DESK_STALE_MS,
    placeholderData: keepPrevious,
    initialData:
      sessionCache?.deskQuoteKey === deskQuoteKey
        ? (sessionCache.deskQuotes as { quotes: Record<string, StockQuote> } | undefined)
        : undefined,
    initialDataUpdatedAt:
      sessionCache?.deskQuoteKey === deskQuoteKey && sessionCache?.deskQuotes
        ? sessionCache.at
        : undefined,
  });

  useEffect(() => {
    if (marketQuotesQ.data) patchDeskCache({ marketQuotes: marketQuotesQ.data });
  }, [marketQuotesQ.data]);
  useEffect(() => {
    if (deskQuotesQ.data && deskQuoteKey) {
      patchDeskCache({ deskQuotes: deskQuotesQ.data, deskQuoteKey });
    }
  }, [deskQuotesQ.data, deskQuoteKey]);

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

  const callsToReview = useMemo(() => {
    const universe = new Set([
      ...holdingsTickers.map((t) => t.toUpperCase()),
      ...(watchlistQ.data?.items ?? []).map((i) => i.ticker.toUpperCase()),
    ]);
    return ratings
      .filter((r) => universe.has(r.ticker.toUpperCase()) && r.rating !== 'HOLD')
      .sort((a, b) => {
        const p = (CALL_PRIORITY[b.rating] ?? 0) - (CALL_PRIORITY[a.rating] ?? 0);
        if (p !== 0) return p;
        return Math.abs(b.score) - Math.abs(a.score);
      })
      .slice(0, CALLS_CAP);
  }, [ratings, holdingsTickers, watchlistQ.data]);

  // Watchlist and holdings-only slices (overlap stays in watchlist).
  const { heatWatchlist, heatHoldings } = useMemo(() => {
    const wl = [...new Set((watchlistQ.data?.items ?? []).map((i) => i.ticker.toUpperCase()))];
    const wlSet = new Set(wl);
    const holdingsOnly = [
      ...new Set(
        holdingsTickers.map((t) => t.toUpperCase()).filter((t) => !wlSet.has(t)),
      ),
    ];
    const watchCap = Math.min(wl.length, HEATMAP_CAP);
    const holdCap = Math.max(0, HEATMAP_CAP - watchCap);
    return {
      heatWatchlist: wl.slice(0, watchCap),
      heatHoldings: holdingsOnly.slice(0, holdCap),
    };
  }, [watchlistQ.data, holdingsTickers]);
  const heatTickers = heatWatchlist.length + heatHoldings.length;

  // Only skeleton when we have nothing to show (no session cache / no data yet)
  const holdingsPending = holdingsQ.isLoading && !holdingsQ.data;
  const marketPending = marketQuotesQ.isLoading && !marketQuotesQ.data;

  const syncAt =
    syncQ.data?.last_sync ?? syncQ.data?.daily?.finished_at ?? syncQ.data?.finished_at ?? null;
  const freshnessLine = `Prices · sync ${fmtDeskTime(syncAt)} · live ${fmtLiveAt(lastLiveAt, liveEnabled)}`;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
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
        <DeskRunActions />
      </div>

      <SyncProgressTracker />
      <AnalysisProgressTracker />

      {holdingsPending ? (
        <Skeleton className="h-8 w-full max-w-xl rounded" />
      ) : (
        <PortfolioSummaryCard summary={summary} />
      )}

      <Panel title="Calls to review" subtitle="Sell / reduce / buy first · then by |score|" dense>
        {callsToReview.length === 0 ? (
          <p className="text-xs text-[var(--color-text-muted)]">Run Analysis to populate calls.</p>
        ) : (
          <div className="flex flex-col gap-0 sm:flex-row sm:flex-wrap sm:gap-x-3 sm:gap-y-1">
            {callsToReview.map((r) => (
              <Link
                key={r.ticker}
                to={`/stock/${r.ticker}`}
                className="flex min-w-0 items-center gap-2 border-b border-[var(--color-surface-3)] py-1 last:border-0 hover:bg-[var(--color-surface-2)] sm:border-b-0 sm:py-0.5"
              >
                <span className="shrink-0 font-mono text-xs font-semibold text-[var(--color-accent)]">
                  {r.ticker}
                </span>
                <RatingBadge rating={r.rating} />
                <span className="font-mono text-xs tabular-nums text-[var(--color-text-secondary)]">
                  {r.score > 0 ? `+${r.score}` : String(r.score)}
                </span>
              </Link>
            ))}
          </div>
        )}
      </Panel>

      <div className="terminal-grid">
        <div className="col-span-12 lg:col-span-8">
          <Panel
            title="Holdings"
            subtitle={`${holdingsTickers.length} positions · ${freshnessLine}`}
          >
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
          <Panel title="Market" subtitle="SPY · QQQ · IWM · DIA" dense>
            <div className="flex flex-col">
              {MARKET_TICKERS.map((t) => {
                const q = quotes[t];
                if (marketPending && !q) {
                  return <Skeleton key={t} className="mb-1 h-7 w-full rounded" />;
                }
                return (
                  <Link
                    key={t}
                    to={`/stock/${t}`}
                    className="flex items-center gap-2 border-b border-[var(--color-surface-3)] py-1.5 last:border-0 hover:bg-[var(--color-surface-2)]"
                  >
                    <span className="w-9 shrink-0 font-mono text-xs font-semibold text-[var(--color-accent)]">
                      {t}
                    </span>
                    <Sparkline data={q?.spark ?? []} width={40} height={14} />
                    <span className="ml-auto font-mono text-xs tabular-nums text-[var(--color-text-primary)]">
                      {q?.latest_close != null ? `$${q.latest_close.toFixed(2)}` : '—'}
                    </span>
                    <DeltaValue value={q?.change_pct} className="w-14 shrink-0 text-right text-[11px]" />
                  </Link>
                );
              })}
            </div>
          </Panel>

          <Panel
            title="Universe heatmap"
            subtitle="Watchlist · holdings"
            actions={
              <Link to="/watchlist" className="btn-terminal">
                Manage
              </Link>
            }
            dense
          >
            {watchlistQ.isLoading && heatTickers === 0 ? (
              <div className="grid grid-cols-2 gap-1.5">
                {Array.from({ length: 6 }).map((_, i) => (
                  <Skeleton key={i} className="h-14 w-full rounded" />
                ))}
              </div>
            ) : heatTickers === 0 ? (
              <p className="text-xs text-[var(--color-text-muted)]">
                Add watchlist tickers or sync holdings to populate the heatmap.
              </p>
            ) : (
              <div className="flex max-h-[min(70vh,520px)] flex-col gap-2.5 overflow-auto">
                {heatWatchlist.length > 0 && (
                  <div>
                    <p className="mb-1.5 text-xs text-[var(--color-text-muted)]">Watchlist</p>
                    <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 lg:grid-cols-2">
                      {heatWatchlist.map((t) => (
                        <HeatTile
                          key={t}
                          ticker={t}
                          price={quotes[t]?.latest_close}
                          changePct={quotes[t]?.change_pct}
                          rating={(ratingMap[t]?.rating as Rating | undefined) ?? null}
                        />
                      ))}
                    </div>
                  </div>
                )}
                {heatWatchlist.length > 0 && heatHoldings.length > 0 && (
                  <div className="border-t border-[var(--gridline)]" aria-hidden="true" />
                )}
                {heatHoldings.length > 0 && (
                  <div>
                    <p className="mb-1.5 text-xs text-[var(--color-text-muted)]">Holdings</p>
                    <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 lg:grid-cols-2">
                      {heatHoldings.map((t) => (
                        <HeatTile
                          key={t}
                          ticker={t}
                          price={quotes[t]?.latest_close}
                          changePct={quotes[t]?.change_pct}
                          rating={(ratingMap[t]?.rating as Rating | undefined) ?? null}
                        />
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}
