import { Link } from 'react-router-dom';
import { useEffect, useMemo, useRef } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { PortfolioSummaryCard } from '../components/PortfolioSummary';
import { HoldingsTable } from '../components/HoldingsTable';
import { SyncHoldingsButton } from '../components/SyncHoldingsButton';
import { DeskRunActions } from '../components/DeskRunActions';
import { LiveSessionIndicator } from '../components/LiveSessionIndicator';
import { JobsPanel } from '../components/JobsPanel';
import { Panel } from '../components/Panel';
import { HeatTile } from '../components/HeatTile';
import { DeltaValue } from '../components/DeltaValue';
import { Sparkline } from '../components/Sparkline';
import { LoadingSpinner, LoadingState } from '../components/LoadingSpinner';
import { AnalysisErrorIcon } from '../components/AnalysisErrorIcon';
import { RatingBadge } from '../components/RatingBadge';
import { WatchlistSuggestions } from '../components/WatchlistSuggestions';
import type { DeskSnapshot, JobsSnapshot, Rating } from '../api/types';
import { useLivePriceRefresh } from '../hooks/useLivePriceRefresh';
import { useUsRegularSession } from '../hooks/useUsRegularSession';
import { isUsRegularSession } from '../lib/usMarketHours';
import { patchDeskCache, readDeskCache } from '../lib/deskCache';
import { scoreTextClass } from '../lib/reportDepth';

const MARKET_TICKERS = ['SPY', 'QQQ', 'IWM', 'DIA'];
/** Heatmap prefers watchlist; holdings fill remaining slots up to this cap. */
const HEATMAP_CAP = 18;
const CALLS_CAP = 6;
const RECENT_ANALYSIS_CAP = 7;

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

/** Hydrate sibling query keys so other pages/buttons still work after invalidation. */
function seedDeskCaches(qc: ReturnType<typeof useQueryClient>, snap: DeskSnapshot) {
  qc.setQueryData(['holdings'], snap.holdings);
  qc.setQueryData(['watchlist'], snap.watchlist);
  const deskKey = (snap.meta.desk_tickers ?? []).join(',');
  if (deskKey) {
    qc.setQueryData(['ratings', 'desk', deskKey], snap.ratings);
  }
  qc.setQueryData(['ratings', 'recent', RECENT_ANALYSIS_CAP], snap.recent_ratings);
  qc.setQueryData(['quotes', 'desk'], snap.quotes);
}

export function DashboardPage() {
  const qc = useQueryClient();
  const marketOpen = useUsRegularSession();

  // Polling owned by useSyncKeepAlive — subscribe only; prefer jobs snapshot cache.
  const syncQ = useQuery({
    queryKey: ['sync-status'],
    queryFn: async () => {
      const snap = qc.getQueryData<JobsSnapshot>(['jobs']);
      if (snap?.sync) return snap.sync;
      return api.getSyncStatus();
    },
    staleTime: 5_000,
  });
  const jobsQ = useQuery({
    queryKey: ['jobs'],
    queryFn: () => api.getJobs(),
    staleTime: 5_000,
  });
  const analysisQ = useQuery({
    queryKey: ['analysis-status'],
    queryFn: async () => {
      const snap = qc.getQueryData<JobsSnapshot>(['jobs']);
      if (snap?.analysis) return snap.analysis;
      return api.getAnalysisStatus();
    },
    staleTime: 5_000,
  });
  const syncing = Boolean(syncQ.data?.running) || syncQ.data?.status === 'running';
  const deskBusy =
    syncing ||
    Boolean(analysisQ.data?.running) ||
    analysisQ.data?.status === 'running' ||
    analysisQ.data?.status === 'pending' ||
    Boolean(
      jobsQ.data?.jobs?.some((j) => j.status === 'queued' || j.status === 'running'),
    );
  // Off-hours prices don't move — full snapshot poll only during US RTH when idle.
  // Jobs keep updating via useSyncKeepAlive; manual sync invalidates snapshot on complete.
  const snapshotPollMs = deskBusy || !marketOpen ? false : DESK_STALE_MS;

  const deskQ = useQuery({
    queryKey: ['desk-snapshot'],
    queryFn: async () => {
      const snap = await api.getDeskSnapshot();
      seedDeskCaches(qc, snap);
      return snap;
    },
    staleTime: DESK_STALE_MS,
    refetchInterval: snapshotPollMs,
    placeholderData: keepPrevious,
    initialData: sessionCache?.snapshot as DeskSnapshot | undefined,
    initialDataUpdatedAt: sessionCache?.snapshot ? sessionCache.at : undefined,
    // Recover after local API restarts (Vite returns 502 while uvicorn is down).
    retry: 3,
    retryDelay: (n) => Math.min(1000 * 2 ** n, 8000),
  });

  const wasRunning = useRef(false);
  useEffect(() => {
    const running = !!analysisQ.data?.running;
    if (wasRunning.current && !running) {
      void qc.invalidateQueries({ queryKey: ['desk-snapshot'] });
      void qc.invalidateQueries({ queryKey: ['ratings'] });
      void qc.invalidateQueries({ queryKey: ['watchlist'] });
      void qc.invalidateQueries({ queryKey: ['report'] });
    }
    wasRunning.current = running;
  }, [analysisQ.data?.running, qc]);

  useEffect(() => {
    if (deskQ.data) patchDeskCache({ snapshot: deskQ.data });
  }, [deskQ.data]);

  const holdings = deskQ.data?.holdings.holdings ?? [];
  const holdingsTickers = holdings.map((h) => h.ticker);
  const watchItems = deskQ.data?.watchlist.items ?? [];
  const ratings = deskQ.data?.ratings.ratings ?? [];
  const recentAnalysis = deskQ.data?.recent_ratings.ratings ?? [];
  const quotes = deskQ.data?.quotes.quotes ?? {};

  const { heatWatchlist, heatHoldings } = useMemo(() => {
    const wl = [...new Set(watchItems.map((i) => i.ticker.toUpperCase()))];
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
  }, [watchItems, holdingsTickers]);
  const heatTickers = heatWatchlist.length + heatHoldings.length;

  const heatQuoteTickers = useMemo(
    () => [...new Set([...heatWatchlist, ...heatHoldings])],
    [heatWatchlist, heatHoldings],
  );

  const liveTickers = useMemo(
    () => [...MARKET_TICKERS, ...heatQuoteTickers],
    [heatQuoteTickers],
  );

  const deskReady = Boolean(deskQ.data);
  const liveEnabled = !syncing && deskReady;
  const { lastLiveAt } = useLivePriceRefresh(liveTickers, {
    enabled: liveEnabled,
    deferMs: 45_000,
  });

  const summary = deskQ.data?.holdings.summary ?? {
    total_value: 0,
    total_unrealized_pnl: 0,
    position_count: 0,
    snapshot_at: null,
  };

  const ratingMap = Object.fromEntries(ratings.map((r) => [r.ticker, r]));

  const callsToReview = useMemo(() => {
    const universe = new Set([
      ...holdingsTickers.map((t) => t.toUpperCase()),
      ...watchItems.map((i) => i.ticker.toUpperCase()),
    ]);
    return ratings
      .filter(
        (r): r is typeof r & { rating: Rating; score: number } =>
          universe.has(r.ticker.toUpperCase()) &&
          r.rating != null &&
          r.score != null &&
          r.rating !== 'HOLD',
      )
      .sort((a, b) => {
        const p = (CALL_PRIORITY[b.rating] ?? 0) - (CALL_PRIORITY[a.rating] ?? 0);
        if (p !== 0) return p;
        return Math.abs(b.score) - Math.abs(a.score);
      })
      .slice(0, CALLS_CAP);
  }, [ratings, holdingsTickers, watchItems]);

  const deskPending = deskQ.isLoading && !deskQ.data;
  const deskError = deskQ.isError && !deskQ.data;

  const syncAt =
    syncQ.data?.last_sync ?? syncQ.data?.daily?.finished_at ?? syncQ.data?.finished_at ?? null;
  const holdingsSyncedAt =
    deskQ.data?.holdings.holdings_synced_at ??
    deskQ.data?.holdings.summary?.holdings_synced_at ??
    null;
  const freshnessLine = [
    `Holdings · ${fmtDeskTime(holdingsSyncedAt)}`,
    `Prices · sync ${fmtDeskTime(syncAt)}`,
    `live ${fmtLiveAt(lastLiveAt, liveEnabled)}`,
  ].join(' · ');

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] sm:items-center">
        <div className="min-w-0">
          <h2 className="font-display text-lg font-semibold">Trading Desk</h2>
          <p className="mt-0.5 flex items-center gap-1.5 text-xs text-[var(--color-text-secondary)]">
            {analysisQ.isLoading ? (
              <>
                <LoadingSpinner size="sm" />
                <span>Checking last analysis…</span>
              </>
            ) : analysisQ.data?.last_run ? (
              `Last analysis ${new Date(analysisQ.data.last_run).toLocaleString()}`
            ) : (
              'No analysis run yet'
            )}
          </p>
        </div>
        <div className="flex justify-center">
          <LiveSessionIndicator />
        </div>
        <div className="flex flex-wrap items-center justify-center gap-3 sm:justify-end">
          <DeskRunActions />
        </div>
      </div>

      <JobsPanel />

      {deskError ? (
        <p className="text-xs text-[var(--color-down)]">
          {deskQ.error instanceof Error ? deskQ.error.message : 'Failed to load desk.'}
        </p>
      ) : null}

      {deskPending ? (
        <LoadingState label="Loading portfolio…" compact minHeight="3rem" />
      ) : (
        <PortfolioSummaryCard summary={summary} />
      )}

      <Panel title="Calls to review" subtitle="Sell / reduce / buy first · then by |score|" dense>
        {callsToReview.length === 0 ? (
          <p className="text-xs text-[var(--color-text-muted)]">Run Analysis to populate calls.</p>
        ) : (
          <div className="flex flex-col gap-0 sm:flex-row sm:flex-wrap sm:gap-x-1 sm:gap-y-0.5">
            {callsToReview.map((r) => (
              <Link
                key={r.ticker}
                to={`/stock/${r.ticker}`}
                className="flex min-w-0 items-center gap-1.5 rounded-full border-b border-[var(--color-surface-3)] px-2 py-0.5 transition-colors last:border-0 hover:border-transparent hover:bg-[var(--color-surface-2)] sm:border-b-0"
              >
                <span className="shrink-0 font-mono text-xs font-semibold text-[var(--color-accent)]">
                  {r.ticker}
                </span>
                {r.rating ? (
                  <RatingBadge rating={r.rating} reportType={r.report_type} />
                ) : (
                  <span className="text-[var(--color-text-muted)]">—</span>
                )}
                <span className={scoreTextClass(r.report_type)}>
                  {r.score == null ? '—' : r.score > 0 ? `+${r.score}` : String(r.score)}
                </span>
              </Link>
            ))}
          </div>
        )}
      </Panel>

      <Panel title="Recent analysis" subtitle="Last 5 days · newest first" dense>
        {deskPending && !recentAnalysis.length ? (
          <p className="text-xs text-[var(--color-text-muted)]">Loading recent analysis…</p>
        ) : deskError ? (
          <p className="text-xs text-[var(--color-down)]">
            {deskQ.error instanceof Error
              ? deskQ.error.message
              : 'Failed to load recent analysis.'}
          </p>
        ) : recentAnalysis.length === 0 ? (
          <p className="text-xs text-[var(--color-text-muted)]">
            No analysis in the last 5 days. Run Analysis to populate.
          </p>
        ) : (
          <div className="flex flex-col gap-0 sm:flex-row sm:flex-nowrap sm:gap-x-1 sm:overflow-x-auto">
            {recentAnalysis.slice(0, RECENT_ANALYSIS_CAP).map((r) => (
              <Link
                key={`${r.id}-${r.ticker}-${r.created_at}`}
                to={`/stock/${r.ticker}`}
                className="flex min-w-0 items-center gap-1.5 rounded-full border-b border-[var(--color-surface-3)] px-2 py-0.5 transition-colors last:border-0 hover:border-transparent hover:bg-[var(--color-surface-2)] sm:border-b-0"
              >
                <span className="shrink-0 font-mono text-xs font-semibold text-[var(--color-accent)]">
                  {r.ticker}
                </span>
                <span className="inline-flex items-center gap-1">
                  {r.rating ? (
                    <RatingBadge rating={r.rating} reportType={r.report_type} />
                  ) : !r.analysis_failed ? (
                    <span className="text-[var(--color-text-muted)]">—</span>
                  ) : null}
                  <AnalysisErrorIcon
                    analysisFailed={r.analysis_failed}
                    analysisError={r.analysis_error}
                    failedAt={r.failed_at}
                  />
                </span>
                <span className={scoreTextClass(r.report_type)}>
                  {r.score == null ? '—' : r.score > 0 ? `+${r.score}` : String(r.score)}
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
            actions={<SyncHoldingsButton />}
          >
            {deskPending ? (
              <LoadingState label="Loading holdings…" minHeight="12rem" />
            ) : (
              <HoldingsTable
                holdings={holdings}
                ratings={ratings}
                quotes={quotes}
              />
            )}
          </Panel>
        </div>

        <div className="col-span-12 flex flex-col gap-3 lg:col-span-4">
          <Panel title="Market" subtitle="SPY · QQQ · IWM · DIA" dense>
            {deskPending ? (
              <LoadingState label="Loading market…" compact minHeight="8rem" />
            ) : (
            <div className="flex flex-col">
              {MARKET_TICKERS.map((t) => {
                const q = quotes[t];
                return (
                  <div
                    key={t}
                    className="flex items-center gap-2 border-b border-[var(--color-surface-3)] py-1.5 last:border-0"
                  >
                    <span className="w-9 shrink-0 font-mono text-xs font-semibold text-[var(--color-accent)]">
                      {t}
                    </span>
                    <Sparkline data={q?.spark ?? []} width={40} height={14} />
                    <span className="ml-auto font-mono text-xs tabular-nums text-[var(--color-text-primary)]">
                      {q?.latest_close != null ? `$${q.latest_close.toFixed(2)}` : '—'}
                    </span>
                    <DeltaValue value={q?.change_pct} className="w-14 shrink-0 text-right text-[11px]" />
                  </div>
                );
              })}
            </div>
            )}
          </Panel>

          <WatchlistSuggestions dense maxRows={8} />

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
            {deskPending && heatTickers === 0 ? (
              <LoadingState label="Loading heatmap…" minHeight="10rem" />
            ) : heatTickers === 0 ? (
              <p className="text-xs text-[var(--color-text-muted)]">
                Add watchlist tickers or sync holdings to populate the heatmap.
              </p>
            ) : (
              <div className="flex max-h-[min(70vh,520px)] flex-col gap-2.5 overflow-auto">
                {heatWatchlist.length > 0 && (
                  <div>
                    <p className="mb-1.5 text-xs text-[var(--color-text-muted)]">Watchlist</p>
                    <div className="heat-mosaic grid-cols-2 sm:grid-cols-3 lg:grid-cols-2">
                      {heatWatchlist.map((t) => (
                        <HeatTile
                          key={t}
                          ticker={t}
                          price={quotes[t]?.latest_close}
                          changePct={quotes[t]?.change_pct}
                          rating={(ratingMap[t]?.rating as Rating | undefined) ?? null}
                          reportType={ratingMap[t]?.report_type}
                          analysisFailed={ratingMap[t]?.analysis_failed}
                          analysisError={ratingMap[t]?.analysis_error}
                          failedAt={ratingMap[t]?.failed_at}
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
                    <div className="heat-mosaic grid-cols-2 sm:grid-cols-3 lg:grid-cols-2">
                      {heatHoldings.map((t) => (
                        <HeatTile
                          key={t}
                          ticker={t}
                          price={quotes[t]?.latest_close}
                          changePct={quotes[t]?.change_pct}
                          rating={(ratingMap[t]?.rating as Rating | undefined) ?? null}
                          reportType={ratingMap[t]?.report_type}
                          analysisFailed={ratingMap[t]?.analysis_failed}
                          analysisError={ratingMap[t]?.analysis_error}
                          failedAt={ratingMap[t]?.failed_at}
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
