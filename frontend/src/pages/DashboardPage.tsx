import { Link } from 'react-router-dom';
import { useEffect, useMemo, useRef } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { PortfolioSummaryCard } from '../components/PortfolioSummary';
import { HoldingsTable } from '../components/HoldingsTable';
import { SyncHoldingsButton } from '../components/SyncHoldingsButton';
import { DeskRunActions } from '../components/DeskRunActions';
import { JobsPanel } from '../components/JobsPanel';
import { Panel } from '../components/Panel';
import { HeatTile } from '../components/HeatTile';
import { DeltaValue } from '../components/DeltaValue';
import { Sparkline } from '../components/Sparkline';
import { LoadingSpinner, LoadingState } from '../components/LoadingSpinner';
import { RatingBadge } from '../components/RatingBadge';
import type { Rating, StockQuote } from '../api/types';
import { useLivePriceRefresh } from '../hooks/useLivePriceRefresh';
import { isUsRegularSession } from '../lib/usMarketHours';
import { patchDeskCache, readDeskCache } from '../lib/deskCache';
import { scoreTextClass } from '../lib/reportDepth';

const MARKET_TICKERS = ['SPY', 'QQQ', 'IWM', 'DIA'];
/** Heatmap prefers watchlist; holdings fill remaining slots up to this cap. */
const HEATMAP_CAP = 18;
const CALLS_CAP = 6;
const RECENT_ANALYSIS_CAP = 8;
const MARKET_SPARK_DAYS = 7;
const HEAT_SPARK_DAYS = 7;
const HOLDINGS_SPARK_DAYS = 5;

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

  // Polling owned by useSyncKeepAlive — subscribe only.
  const syncQ = useQuery({
    queryKey: ['sync-status'],
    queryFn: api.getSyncStatus,
    staleTime: 5_000,
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
  const watchlistQ = useQuery({
    queryKey: ['watchlist'],
    queryFn: api.getWatchlist,
    staleTime: DESK_STALE_MS,
    placeholderData: keepPrevious,
    initialData: sessionCache?.watchlist as Awaited<ReturnType<typeof api.getWatchlist>> | undefined,
    initialDataUpdatedAt: sessionCache?.watchlist ? sessionCache.at : undefined,
  });

  const holdingsTickers = (holdingsQ.data?.holdings ?? []).map((h) => h.ticker);

  const deskTickers = useMemo(() => {
    const fromHoldings = holdingsTickers.map((t) => t.toUpperCase());
    const fromWatch = (watchlistQ.data?.items ?? []).map((i) => i.ticker.toUpperCase());
    return [...new Set([...fromHoldings, ...fromWatch])].sort();
  }, [holdingsTickers, watchlistQ.data]);
  const deskTickerKey = deskTickers.join(',');

  const ratingsQ = useQuery({
    queryKey: ['ratings', 'desk', deskTickerKey],
    queryFn: () => api.getRatings(deskTickers),
    enabled: deskTickers.length > 0,
    refetchInterval: syncing ? false : DESK_STALE_MS,
    staleTime: DESK_STALE_MS,
    placeholderData: keepPrevious,
    initialData:
      sessionCache?.ratingsDeskKey === deskTickerKey
        ? (sessionCache.ratings as Awaited<ReturnType<typeof api.getRatings>> | undefined)
        : undefined,
    initialDataUpdatedAt:
      sessionCache?.ratingsDeskKey === deskTickerKey && sessionCache?.ratings
        ? sessionCache.at
        : undefined,
  });

  const recentRatingsQ = useQuery({
    queryKey: ['ratings', 'recent', RECENT_ANALYSIS_CAP],
    queryFn: () => api.getRecentRatings(RECENT_ANALYSIS_CAP),
    refetchInterval: syncing ? false : DESK_STALE_MS,
    staleTime: DESK_STALE_MS,
    placeholderData: keepPrevious,
  });

  const analysisQ = useQuery({
    queryKey: ['analysis-status'],
    queryFn: api.getAnalysisStatus,
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
    if (ratingsQ.data && deskTickerKey) {
      patchDeskCache({ ratings: ratingsQ.data, ratingsDeskKey: deskTickerKey });
    }
  }, [ratingsQ.data, deskTickerKey]);
  useEffect(() => {
    if (watchlistQ.data) patchDeskCache({ watchlist: watchlistQ.data });
  }, [watchlistQ.data]);

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

  const heatQuoteTickers = useMemo(
    () => [...new Set([...heatWatchlist, ...heatHoldings])],
    [heatWatchlist, heatHoldings],
  );
  const heatQuoteKey = heatQuoteTickers.join(',');

  const holdingsRestTickers = useMemo(() => {
    const heatSet = new Set(heatQuoteTickers);
    return [
      ...new Set(holdingsTickers.map((t) => t.toUpperCase()).filter((t) => !heatSet.has(t))),
    ].sort();
  }, [holdingsTickers, heatQuoteTickers]);
  const holdingsRestQuoteKey = holdingsRestTickers.join(',');

  const liveTickers = useMemo(
    () => [...MARKET_TICKERS, ...heatQuoteTickers],
    [heatQuoteTickers],
  );

  const deskReady = Boolean(holdingsQ.data || watchlistQ.data);
  const liveEnabled = !syncing && deskReady;
  const { lastLiveAt } = useLivePriceRefresh(liveTickers, {
    enabled: liveEnabled,
    deferMs: 45_000,
  });

  const marketQuotesQ = useQuery({
    queryKey: ['quotes', 'market', MARKET_TICKERS.join(',')],
    queryFn: () => api.getQuotes(MARKET_TICKERS, MARKET_SPARK_DAYS),
    staleTime: DESK_STALE_MS,
    refetchInterval: syncing ? false : DESK_STALE_MS,
    placeholderData: keepPrevious,
    initialData: sessionCache?.marketQuotes as
      | { quotes: Record<string, StockQuote> }
      | undefined,
    initialDataUpdatedAt: sessionCache?.marketQuotes ? sessionCache.at : undefined,
  });

  const heatQuotesQ = useQuery({
    queryKey: ['quotes', 'heat', heatQuoteKey],
    queryFn: () => api.getQuotes(heatQuoteTickers, HEAT_SPARK_DAYS),
    enabled: heatQuoteTickers.length > 0,
    staleTime: DESK_STALE_MS,
    refetchInterval: syncing ? false : DESK_STALE_MS,
    placeholderData: keepPrevious,
    initialData:
      sessionCache?.heatQuoteKey === heatQuoteKey
        ? (sessionCache.heatQuotes as { quotes: Record<string, StockQuote> } | undefined)
        : undefined,
    initialDataUpdatedAt:
      sessionCache?.heatQuoteKey === heatQuoteKey && sessionCache?.heatQuotes
        ? sessionCache.at
        : undefined,
  });

  const holdingsRestQuotesQ = useQuery({
    queryKey: ['quotes', 'holdings-rest', holdingsRestQuoteKey],
    queryFn: () => api.getQuotes(holdingsRestTickers, HOLDINGS_SPARK_DAYS),
    enabled:
      holdingsRestTickers.length > 0 &&
      Boolean(holdingsQ.data) &&
      (heatQuoteTickers.length === 0 || heatQuotesQ.isSuccess),
    staleTime: DESK_STALE_MS,
    refetchInterval: syncing ? false : DESK_STALE_MS,
    placeholderData: keepPrevious,
    initialData:
      sessionCache?.holdingsRestQuoteKey === holdingsRestQuoteKey
        ? (sessionCache.holdingsRestQuotes as { quotes: Record<string, StockQuote> } | undefined)
        : undefined,
    initialDataUpdatedAt:
      sessionCache?.holdingsRestQuoteKey === holdingsRestQuoteKey &&
      sessionCache?.holdingsRestQuotes
        ? sessionCache.at
        : undefined,
  });

  useEffect(() => {
    if (marketQuotesQ.data) patchDeskCache({ marketQuotes: marketQuotesQ.data });
  }, [marketQuotesQ.data]);
  useEffect(() => {
    if (heatQuotesQ.data && heatQuoteKey) {
      patchDeskCache({ heatQuotes: heatQuotesQ.data, heatQuoteKey });
    }
  }, [heatQuotesQ.data, heatQuoteKey]);
  useEffect(() => {
    if (holdingsRestQuotesQ.data && holdingsRestQuoteKey) {
      patchDeskCache({
        holdingsRestQuotes: holdingsRestQuotesQ.data,
        holdingsRestQuoteKey,
      });
    }
  }, [holdingsRestQuotesQ.data, holdingsRestQuoteKey]);

  const quotes = useMemo(
    () => ({
      ...(marketQuotesQ.data?.quotes ?? {}),
      ...(heatQuotesQ.data?.quotes ?? {}),
      ...(holdingsRestQuotesQ.data?.quotes ?? {}),
    }),
    [marketQuotesQ.data, heatQuotesQ.data, holdingsRestQuotesQ.data],
  );

  const summary = holdingsQ.data?.summary ?? {
    total_value: 0,
    total_unrealized_pnl: 0,
    position_count: 0,
    snapshot_at: null,
  };

  const ratings = ratingsQ.data?.ratings ?? [];
  const ratingMap = Object.fromEntries(ratings.map((r) => [r.ticker, r]));

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

  const recentAnalysis = recentRatingsQ.data?.ratings ?? [];

  const holdingsPending = holdingsQ.isLoading && !holdingsQ.data;
  const marketPending = marketQuotesQ.isLoading && !marketQuotesQ.data;

  const syncAt =
    syncQ.data?.last_sync ?? syncQ.data?.daily?.finished_at ?? syncQ.data?.finished_at ?? null;
  const holdingsSyncedAt =
    holdingsQ.data?.holdings_synced_at ??
    holdingsQ.data?.summary?.holdings_synced_at ??
    null;
  const freshnessLine = [
    `Holdings · ${fmtDeskTime(holdingsSyncedAt)}`,
    `Prices · sync ${fmtDeskTime(syncAt)}`,
    `live ${fmtLiveAt(lastLiveAt, liveEnabled)}`,
  ].join(' · ');

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
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
        <DeskRunActions />
      </div>

      <JobsPanel />

      {holdingsPending ? (
        <LoadingState label="Loading portfolio…" compact minHeight="3rem" />
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
                <RatingBadge rating={r.rating} reportType={r.report_type} />
                <span className={scoreTextClass(r.report_type)}>
                  {r.score > 0 ? `+${r.score}` : String(r.score)}
                </span>
              </Link>
            ))}
          </div>
        )}
      </Panel>

      <Panel title="Recent analysis" subtitle="Last 5 days · newest first" dense>
        {recentRatingsQ.isLoading && !recentAnalysis.length ? (
          <p className="text-xs text-[var(--color-text-muted)]">Loading recent analysis…</p>
        ) : recentRatingsQ.isError ? (
          <p className="text-xs text-[var(--color-down)]">
            {recentRatingsQ.error instanceof Error
              ? recentRatingsQ.error.message
              : 'Failed to load recent analysis.'}
          </p>
        ) : recentAnalysis.length === 0 ? (
          <p className="text-xs text-[var(--color-text-muted)]">
            No analysis in the last 5 days. Run Analysis to populate.
          </p>
        ) : (
          <div className="flex flex-col gap-0 sm:flex-row sm:flex-wrap sm:gap-x-3 sm:gap-y-1">
            {recentAnalysis.map((r) => (
              <Link
                key={`${r.id}-${r.ticker}-${r.created_at}`}
                to={`/stock/${r.ticker}`}
                className="flex min-w-0 items-center gap-2 border-b border-[var(--color-surface-3)] py-1 last:border-0 hover:bg-[var(--color-surface-2)] sm:border-b-0 sm:py-0.5"
              >
                <span className="shrink-0 font-mono text-xs font-semibold text-[var(--color-accent)]">
                  {r.ticker}
                </span>
                <RatingBadge rating={r.rating} reportType={r.report_type} />
                <span className={scoreTextClass(r.report_type)}>
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
            actions={<SyncHoldingsButton />}
          >
            {holdingsPending ? (
              <LoadingState label="Loading holdings…" minHeight="12rem" />
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
            {marketPending ? (
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
                    <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 lg:grid-cols-2">
                      {heatWatchlist.map((t) => (
                        <HeatTile
                          key={t}
                          ticker={t}
                          price={quotes[t]?.latest_close}
                          changePct={quotes[t]?.change_pct}
                          rating={(ratingMap[t]?.rating as Rating | undefined) ?? null}
                          reportType={ratingMap[t]?.report_type}
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
                          reportType={ratingMap[t]?.report_type}
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
