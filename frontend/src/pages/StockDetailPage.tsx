import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { useParams, Link, useLocation } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type { ReportTask, ResearchReport } from '../api/types';
import { RatingBadge } from '../components/RatingBadge';
import { ScoreMeter } from '../components/ScoreMeter';
import { Panel } from '../components/Panel';
import { DeltaValue } from '../components/DeltaValue';
import { Sparkline } from '../components/Sparkline';
import { FactorBars } from '../components/FactorBars';
import { SectionAccordion } from '../components/SectionAccordion';
import { DecisionBrief } from '../components/DecisionBrief';
import { DecisionSnapshot } from '../components/DecisionSnapshot';
import { ChartLoading, LoadingSpinner, LoadingState } from '../components/LoadingSpinner';
import {
  ChartRangeToggle,
  chartRangeHint,
  type ChartRangeId,
} from '../components/ChartRangeToggle';
import { RecentReportsPanel } from '../components/RecentReportsPanel';
import { useLivePriceRefresh } from '../hooks/useLivePriceRefresh';

const PriceChart = lazy(() =>
  import('../components/PriceChart').then((m) => ({ default: m.PriceChart })),
);
const RatingHistoryChart = lazy(() =>
  import('../components/RatingHistoryChart').then((m) => ({ default: m.RatingHistoryChart })),
);
const ReportMarkdown = lazy(() =>
  import('../components/ReportMarkdown').then((m) => ({ default: m.ReportMarkdown })),
);
const ForecastChart = lazy(() =>
  import('../components/ForecastChart').then((m) => ({ default: m.ForecastChart })),
);

function ChartFallback() {
  return <ChartLoading />;
}

const CORE_LABELS: Record<string, string> = {
  market: 'Market / Technicals',
  fundamentals: 'Fundamentals',
  news: 'News / Macro',
  sentiment: 'Sentiment',
};

const DEEP_LABELS: Record<string, string> = {
  flows: 'Hot Money / Flows',
  policy: 'Policy',
  lockup: 'Lockup',
  kronos: 'Kronos Forecast',
};

const DEBATE_LABELS: Record<string, string> = {
  research_plan: 'Research Plan',
  trader_plan: 'Trader Proposal',
  portfolio_decision: 'Portfolio Decision',
};

function taskStorageKey(ticker: string) {
  return `research-task:${ticker}`;
}

function persistTask(ticker: string, taskId: string, reportType: 'core' | 'deep') {
  try {
    sessionStorage.setItem(taskStorageKey(ticker), JSON.stringify({ taskId, reportType }));
  } catch { /* ignore */ }
}

function clearPersistedTask(ticker: string) {
  try {
    sessionStorage.removeItem(taskStorageKey(ticker));
  } catch { /* ignore */ }
}

function readPersistedTask(ticker: string): { taskId: string; reportType: 'core' | 'deep' } | null {
  try {
    const raw = sessionStorage.getItem(taskStorageKey(ticker));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { taskId?: string; reportType?: string };
    if (!parsed.taskId || (parsed.reportType !== 'core' && parsed.reportType !== 'deep')) return null;
    return { taskId: parsed.taskId, reportType: parsed.reportType };
  } catch {
    return null;
  }
}

function fmtPrice(n: number | null | undefined) {
  if (n == null) return '—';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(n);
}

export function StockDetailPage() {
  const { ticker = '' } = useParams();
  const t = ticker.toUpperCase();
  const location = useLocation();
  const qc = useQueryClient();
  const reportRef = useRef<HTMLDivElement>(null);

  const [generating, setGenerating] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [generateType, setGenerateType] = useState<'core' | 'deep'>('core');

  const resumeTask = (id: string, reportType: 'core' | 'deep') => {
    setTaskId(id);
    setGenerateType(reportType);
    setGenerating(true);
    persistTask(t, id, reportType);
  };

  // Scroll to report when arriving via /report alias or #report hash
  useEffect(() => {
    const wantsReport =
      location.hash === '#report' || location.pathname.endsWith('/report');
    if (wantsReport && reportRef.current) {
      reportRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, [location.hash, location.pathname, t]);

  const [chartRange, setChartRange] = useState<ChartRangeId>('90');

  useLivePriceRefresh(t ? [t] : [], { enabled: !!t });

  const quoteQ = useQuery({
    queryKey: ['quotes', t],
    queryFn: () => api.getQuotes([t]),
    enabled: !!t,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
  const chartQ = useQuery({
    queryKey: ['chart', t, chartRange],
    queryFn: () => api.getChart(t, 'close', chartRange),
    enabled: !!t,
    staleTime: 60_000,
  });
  // Chronologically latest report (core or deep) — matches desk ratings after weekly analysis.
  const reportQuery = useQuery({
    queryKey: ['report', t, 'latest'],
    queryFn: () => api.getReportIfExists(t, 'latest'),
    enabled: !!t && !generating,
    retry: 2,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 4000),
    staleTime: 60_000,
  });

  // First-paint settled: defer secondary DB reads so we don't exhaust the pool.
  const primarySettled =
    !!t &&
    !generating &&
    (quoteQ.isFetched || quoteQ.isError) &&
    (reportQuery.isFetched || reportQuery.isError);

  const technicalsQ = useQuery({
    queryKey: ['technicals', t],
    queryFn: () => api.getTechnicals(t),
    enabled: primarySettled,
    staleTime: 60_000,
  });
  const historyQ = useQuery({
    queryKey: ['ratings', t],
    queryFn: () => api.getRatingHistory(t),
    enabled: primarySettled,
    staleTime: 60_000,
  });
  const watchlistQ = useQuery({
    queryKey: ['watchlist'],
    queryFn: api.getWatchlist,
    staleTime: 60_000,
  });
  const newsQ = useQuery({
    queryKey: ['news', t],
    queryFn: () => api.getRecentNews(t, 15),
    enabled: primarySettled,
    staleTime: 60_000,
  });

  const activeTaskQuery = useQuery({
    queryKey: ['report-active', t],
    queryFn: () => api.getActiveReportTask(t),
    enabled: !!t,
    retry: 1,
    staleTime: 5_000,
  });

  useEffect(() => {
    if (!t || generating || taskId) return;
    const active = activeTaskQuery.data?.task;
    if (active && (active.status === 'pending' || active.status === 'running')) {
      resumeTask(active.task_id, active.report_type);
      return;
    }
    const persisted = readPersistedTask(t);
    if (!persisted || activeTaskQuery.isLoading || activeTaskQuery.isFetching) return;
    api.getTaskStatus(persisted.taskId)
      .then((status) => {
        if (status.status === 'pending' || status.status === 'running') {
          resumeTask(status.task_id, status.report_type);
        } else {
          clearPersistedTask(t);
          if (status.status === 'done') {
            qc.invalidateQueries({ queryKey: ['report', t] });
          }
        }
      })
      .catch(() => clearPersistedTask(t));
  }, [t, activeTaskQuery.data, activeTaskQuery.isLoading, activeTaskQuery.isFetching, generating, taskId]);

  const { data: taskStatus } = useQuery<ReportTask | null>({
    queryKey: ['report-task', taskId],
    queryFn: () => (taskId ? api.getTaskStatus(taskId) : null),
    enabled: !!taskId && generating,
    refetchInterval: () => {
      if (!taskId || !generating) return false;
      if (typeof document !== 'undefined' && document.visibilityState !== 'visible') {
        return false;
      }
      return 2500;
    },
    refetchIntervalInBackground: false,
  });

  useEffect(() => {
    if (taskStatus?.status === 'done') {
      setGenerating(false);
      setTaskId(null);
      clearPersistedTask(t);
      qc.invalidateQueries({ queryKey: ['report-active', t] });
      qc.invalidateQueries({ queryKey: ['jobs'] });
      qc.invalidateQueries({ queryKey: ['ratings'] });
      qc.invalidateQueries({ queryKey: ['ratings', t] });
      qc.invalidateQueries({ queryKey: ['watchlist'] });
      qc.invalidateQueries({ queryKey: ['report', t] });
      qc.invalidateQueries({ queryKey: ['report-history', t] });
      reportQuery.refetch();
    }
    if (taskStatus?.status === 'failed' || taskStatus?.status === 'cancelled') {
      setGenerating(false);
      setTaskId(null);
      clearPersistedTask(t);
      qc.invalidateQueries({ queryKey: ['report-active', t] });
      qc.invalidateQueries({ queryKey: ['jobs'] });
    }
  }, [taskStatus?.status, t]);

  const generateCore = useMutation({
    mutationFn: () => api.generateReport(t),
    onSuccess: (data) => {
      resumeTask(data.task_id, 'core');
      qc.invalidateQueries({ queryKey: ['report-active', t] });
      qc.invalidateQueries({ queryKey: ['jobs'] });
    },
  });
  const generateDeep = useMutation({
    mutationFn: () => api.generateDeepReport(t),
    onSuccess: (data) => {
      resumeTask(data.task_id, 'deep');
      qc.invalidateQueries({ queryKey: ['report-active', t] });
      qc.invalidateQueries({ queryKey: ['jobs'] });
    },
  });

  const cancelJobMut = useMutation({
    mutationFn: (id: string) => api.cancelJob(id),
    onSuccess: () => {
      setGenerating(false);
      setTaskId(null);
      clearPersistedTask(t);
      qc.invalidateQueries({ queryKey: ['report-active', t] });
      qc.invalidateQueries({ queryKey: ['jobs'] });
    },
  });

  const latest = historyQ.data?.history?.[0];
  const onWatchlist = watchlistQ.data?.items.some((i) => i.ticker === t);
  const quote = quoteQ.data?.quotes?.[t];
  const tech = technicalsQ.data;

  const report: ResearchReport | null = reportQuery.data ?? null;
  const reportPending =
    !generating &&
    !!t &&
    (reportQuery.isLoading || reportQuery.isFetching) &&
    !reportQuery.data;
  const hasDeep = report?.report_type === 'deep';
  const sections = report?.sections || {};
  const sectionIds = Object.keys(sections).filter(
    (k) => sections[k] && !k.startsWith('_'),
  );

  const toggleWatchlist = useMutation({
    mutationFn: async () => {
      if (onWatchlist) await api.removeWatchlist(t);
      else await api.addWatchlist(t);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['watchlist'] }),
  });

  if (!t) {
    return <div className="p-8 text-[var(--color-text-muted)]">No ticker specified.</div>;
  }

  return (
    <div className="flex flex-col gap-3 animate-fade-up">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Link to="/" className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-accent)]">
            ← Desk
          </Link>
          <div className="mt-1 flex flex-wrap items-baseline gap-3">
            <h2 className="font-display font-mono text-2xl font-semibold">{t}</h2>
            <span className="font-mono text-2xl font-medium">
              {fmtPrice(quote?.latest_close ?? report?.live_price)}
            </span>
            <DeltaValue value={quote?.change_pct} className="text-base" />
            {quote?.spark && <Sparkline data={quote.spark} width={80} height={24} />}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            {(report?.rating?.rating || latest?.rating) && (
              <RatingBadge
                rating={(report?.rating?.rating || latest?.rating)!}
                reportType={report?.report_type ?? latest?.report_type}
              />
            )}
            {(report?.rating?.score ?? latest?.score) != null && (
              <ScoreMeter
                value={(report?.rating?.score ?? latest?.score)!}
                size="md"
                reportType={report?.report_type ?? latest?.report_type}
              />
            )}
            {report?.entry_levels && (
              <span className="font-mono text-[11px] text-[var(--color-text-muted)]">
                E {fmtPrice(report.entry_levels.entry)} · S {fmtPrice(report.entry_levels.stop)} · T {fmtPrice(report.entry_levels.target)}
              </span>
            )}
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <button
            type="button"
            className="btn-terminal"
            onClick={() => toggleWatchlist.mutate()}
            disabled={toggleWatchlist.isPending}
          >
            {onWatchlist ? 'Unwatch' : 'Watch'}
          </button>
          <button
            type="button"
            className="btn-terminal"
            onClick={() => generateCore.mutate()}
            disabled={generateCore.isPending || generating}
          >
            {generating && generateType === 'core'
              ? 'Generating…'
              : report
                ? 'Regenerate'
                : 'Generate report'}
          </button>
          <button
            type="button"
            className="btn-terminal btn-terminal--accent"
            onClick={() => generateDeep.mutate()}
            disabled={generateDeep.isPending || generating}
          >
            {generating && generateType === 'deep' ? 'Deep dive…' : 'Deep dive'}
          </button>
          {generating && taskId ? (
            <button
              type="button"
              className="btn-terminal"
              disabled={cancelJobMut.isPending}
              onClick={() => cancelJobMut.mutate(taskId)}
            >
              {cancelJobMut.isPending ? 'Cancelling…' : 'Cancel'}
            </button>
          ) : null}
          <a href="#report" className="btn-terminal">Report ↓</a>
        </div>
      </div>

      <div className="terminal-grid">
        {/* Main column */}
        <div className="col-span-12 flex flex-col gap-3 lg:col-span-8">
          <Panel
            title="Price"
            subtitle={
              chartQ.data?.interval
                ? `${chartRangeHint(chartRange)} · ${chartQ.data.interval}${
                    chartRange === '1' && chartQ.data.session_date
                      ? ` · ${chartQ.data.session_date} ET`
                      : ''
                  }`
                : chartRangeHint(chartRange)
            }
            actions={
              <ChartRangeToggle value={chartRange} onChange={setChartRange} />
            }
          >
            {chartQ.isLoading ? (
              <ChartLoading />
            ) : chartQ.isError ? (
              <p className="text-xs text-[var(--color-down)]">
                {chartQ.error instanceof Error ? chartQ.error.message : 'Failed to load chart'}
              </p>
            ) : (
              <Suspense fallback={<ChartFallback />}>
                <PriceChart
                  data={chartQ.data?.result ?? []}
                  range={chartRange}
                  interval={chartQ.data?.interval}
                  sessionDate={chartQ.data?.session_date}
                />
              </Suspense>
            )}
          </Panel>

          <Panel title="Technicals" dense>
            {technicalsQ.isLoading ? (
              <LoadingState label="Loading technicals…" compact minHeight="6rem" />
            ) : !tech?.available ? (
              <p className="text-xs text-[var(--color-text-muted)]">
                Sync price data to compute technicals.
              </p>
            ) : (
              <div className="technicals-grid">
                <div className="technicals-grid__item"><span>RSI (14)</span><span>{tech.rsi_14?.toFixed(1) ?? '—'}</span></div>
                <div className="technicals-grid__item"><span>ATR %</span><span>{tech.atr_pct?.toFixed(2) ?? '—'}%</span></div>
                <div className="technicals-grid__item"><span>SMA 20</span><span>{fmtPrice(tech.sma_20)}</span></div>
                <div className="technicals-grid__item"><span>SMA 50</span><span>{fmtPrice(tech.sma_50)}</span></div>
                <div className="technicals-grid__item"><span>SMA 200</span><span>{fmtPrice(tech.sma_200)}</span></div>
                <div className="technicals-grid__item"><span>MACD hist</span><span>{tech.macd?.histogram?.toFixed(3) ?? '—'}</span></div>
                <div className="technicals-grid__item"><span>52w high</span><span>{fmtPrice(tech.high_52w)}</span></div>
                <div className="technicals-grid__item"><span>52w low</span><span>{fmtPrice(tech.low_52w)}</span></div>
              </div>
            )}
          </Panel>

          {report?.factor_scores && (
            <Panel title="Factor scores" dense>
              <FactorBars scores={report.factor_scores} />
            </Panel>
          )}

          <div ref={reportRef} id="report" style={{ scrollMarginTop: 64 }}>
            <Panel
              title="Research report"
              subtitle={
                report?.created_at
                  ? `Generated ${new Date(report.created_at).toLocaleString()}${hasDeep ? ' · Deep dive' : ' · Core'}`
                  : 'AI multi-factor analysis'
              }
            >
              {generating && (
                <div className="py-8 text-center">
                  <div className="mb-3 flex justify-center">
                    <LoadingSpinner size="lg" />
                  </div>
                  <p className="text-sm font-semibold">
                    Generating {generateType === 'deep' ? 'deep dive' : 'core'} report…
                  </p>
                  <p className="mt-1 text-xs text-[var(--color-text-muted)]">
                    Usually 15–45s. Status survives navigation.
                  </p>
                  {taskId ? (
                    <button
                      type="button"
                      className="btn-terminal mt-3"
                      disabled={cancelJobMut.isPending}
                      onClick={() => cancelJobMut.mutate(taskId)}
                    >
                      {cancelJobMut.isPending ? 'Cancelling…' : 'Cancel job'}
                    </button>
                  ) : null}
                  {taskStatus?.status === 'failed' && (
                    <p className="mt-2 text-xs text-[var(--color-sell)]">{taskStatus.error}</p>
                  )}
                </div>
              )}

              {!generating && reportPending && (
                <LoadingState label="Loading report…" minHeight="12rem" />
              )}

              {!generating && report && (
                <Suspense fallback={<ChartFallback />}>
                  <div className="flex flex-col gap-2">
                    {/* Structured summary: rating, score, levels, drivers — no essay */}
                    <DecisionBrief report={report} />
                    {/* Full AI thesis — markdown rendered once here */}
                    {report.rating?.reasoning ? (
                      <SectionAccordion
                        id="sec-thesis"
                        title="Thesis & reasoning"
                        defaultOpen
                      >
                        <div className="report-prose">
                          <ReportMarkdown content={report.rating.reasoning} />
                        </div>
                      </SectionAccordion>
                    ) : null}
                    {sectionIds.filter((k) => k in CORE_LABELS).map((id) => (
                      <SectionAccordion key={id} id={`sec-${id}`} title={CORE_LABELS[id]} defaultOpen={false}>
                        <ReportMarkdown content={sections[id]} />
                      </SectionAccordion>
                    ))}
                    {sectionIds.filter((k) => k in DEEP_LABELS).map((id) => (
                      <SectionAccordion key={id} id={`sec-${id}`} title={DEEP_LABELS[id]}>
                        <ReportMarkdown content={sections[id]} />
                      </SectionAccordion>
                    ))}
                    {(() => {
                      const kronos = (
                        report.sections as Record<string, unknown> | undefined
                      )?._kronos_data as
                        | {
                            forecast: import('../api/types').ForecastPoint[];
                            last_actual: number;
                            last_date: string;
                          }
                        | undefined;
                      if (!report.sections?.kronos || !kronos?.forecast?.length) return null;
                      return (
                        <ForecastChart
                          forecast={kronos.forecast}
                          lastActual={kronos.last_actual || 0}
                          lastDate={kronos.last_date || ''}
                        />
                      );
                    })()}
                    {sectionIds.filter((k) => k in DEBATE_LABELS).map((id) => (
                      <SectionAccordion key={id} id={`sec-${id}`} title={DEBATE_LABELS[id]}>
                        <ReportMarkdown content={sections[id]} />
                      </SectionAccordion>
                    ))}
                  </div>
                </Suspense>
              )}

              {!generating && !report && !reportPending && (
                <div className="py-6 text-center">
                  <p className="text-sm text-[var(--color-text-secondary)]">No saved report yet.</p>
                  <p className="mt-1 text-xs text-[var(--color-text-muted)]">
                    {generateCore.isPending
                      ? 'Starting generation…'
                      : 'Use Generate report or Deep dive above when you want a new analysis.'}
                  </p>
                </div>
              )}
            </Panel>
          </div>

          <Panel title="Rating history" dense>
            {historyQ.isLoading ? (
              <ChartLoading label="Loading rating history…" />
            ) : (
            <Suspense fallback={<ChartFallback />}>
              <RatingHistoryChart history={historyQ.data?.history ?? []} />
            </Suspense>
            )}
          </Panel>
        </div>

        {/* Right rail */}
        <div className="col-span-12 flex flex-col gap-3 lg:col-span-4">
          <Panel title="Key stats" dense>
            <div className="technicals-grid">
              <div className="technicals-grid__item"><span>Last</span><span>{fmtPrice(quote?.latest_close)}</span></div>
              <div className="technicals-grid__item"><span>Prior</span><span>{fmtPrice(quote?.prior_close)}</span></div>
              <div className="technicals-grid__item"><span>Day %</span><span><DeltaValue value={quote?.change_pct} /></span></div>
              <div className="technicals-grid__item"><span>As of</span><span className="!font-body text-[11px]">{quote?.as_of ? new Date(quote.as_of).toLocaleDateString() : '—'}</span></div>
            </div>
          </Panel>

          {(report?.rating || latest) && (
            <Panel title="AI decision" dense>
              <DecisionSnapshot
                rating={(report?.rating?.rating || latest?.rating)!}
                score={(report?.rating?.score ?? latest?.score) ?? 0}
                reportType={report?.report_type ?? latest?.report_type}
                posture={report?.rating?.posture}
                onJumpToThesis={
                  report?.rating?.reasoning
                    ? () => {
                        document
                          .getElementById('sec-thesis')
                          ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                      }
                    : undefined
                }
              />
            </Panel>
          )}

          <Panel title="News stream" dense>
            {newsQ.isLoading ? (
              <LoadingState label="Loading news…" compact minHeight="6rem" />
            ) : (
              <div className="news-stream">
                {(newsQ.data?.articles ?? []).map((a, i) => (
                  <div key={`${a.link || a.headline}-${i}`} className="news-stream__item">
                    {a.link ? (
                      <a href={a.link} target="_blank" rel="noopener noreferrer" className="news-stream__headline hover:text-[var(--color-accent)]">
                        {a.headline}
                      </a>
                    ) : (
                      <p className="news-stream__headline">{a.headline}</p>
                    )}
                    <p className="news-stream__meta">
                      {[a.source, a.posted ? new Date(a.posted).toLocaleString() : null].filter(Boolean).join(' · ')}
                    </p>
                  </div>
                ))}
                {!newsQ.data?.articles?.length && (
                  <p className="text-xs text-[var(--color-text-muted)]">
                    No news yet — sync data from the desk.
                  </p>
                )}
              </div>
            )}
          </Panel>

          <RecentReportsPanel ticker={t} />
        </div>
      </div>
    </div>
  );
}
