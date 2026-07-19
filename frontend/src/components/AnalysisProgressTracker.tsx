import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { Panel } from './Panel';
import { RatingBadge } from './RatingBadge';
import { ScoreMeter } from './ScoreMeter';
import type { AnalysisProgress } from '../api/types';

const CORE_STAGES = [
  { id: 'gather_prices', label: 'Technicals' },
  { id: 'gather_fundamentals', label: 'Fundamentals' },
  { id: 'gather_news', label: 'News' },
  { id: 'gather_sentiment', label: 'Sentiment' },
  { id: 'synthesize_decision', label: 'Decision' },
  { id: 'persist', label: 'Save' },
];

const RESCORE_STAGES = [
  { id: 'synthesize_decision', label: 'Decision' },
  { id: 'persist', label: 'Save' },
];

function stageIndex(stages: { id: string }[], stage: string | null): number {
  if (!stage) return -1;
  return stages.findIndex((s) => s.id === stage);
}

export function AnalysisProgressTracker() {
  const qc = useQueryClient();

  const statusQ = useQuery({
    queryKey: ['analysis-status'],
    queryFn: api.getAnalysisStatus,
    refetchInterval: (q) => {
      const d = q.state.data as AnalysisProgress | undefined;
      return d?.running ? 800 : 15000;
    },
  });

  const cancelMut = useMutation({
    mutationFn: api.cancelAnalysis,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['analysis-status'] }),
  });

  const data = statusQ.data;
  if (!data) return null;

  const active = data.running || data.status === 'pending' || data.status === 'running';
  const showDone = !active && (data.status === 'done' || data.status === 'failed' || data.status === 'cancelled');
  if (!active && !showDone) return null;
  if (showDone && data.finished_at) {
    const age = Date.now() - new Date(data.finished_at).getTime();
    if (age > 90_000) return null;
  }

  const isRescore = data.mode === 'rescore';
  const stages = isRescore ? RESCORE_STAGES : CORE_STAGES;
  const currentStageIdx = stageIndex(stages, data.stage);
  const doneCount = data.completed?.length ?? 0;
  const total = data.total || data.tickers?.length || 0;

  return (
    <Panel
      title={isRescore ? 'Rescore progress' : 'Analysis progress'}
      subtitle={
        data.message ||
        (isRescore
          ? 'Updating scores & ratings from saved reports'
          : 'Generating core research reports + ratings')
      }
      dense
      actions={
        active ? (
          <button
            type="button"
            className="btn-terminal"
            disabled={cancelMut.isPending}
            onClick={() => cancelMut.mutate()}
          >
            {cancelMut.isPending ? 'Cancelling…' : 'Cancel'}
          </button>
        ) : undefined
      }
    >
      <div className="mb-2">
        <div className="mb-1 flex items-center justify-between gap-2 text-[11px] text-[var(--color-text-muted)]">
          <span className="font-mono">
            {active
              ? `${doneCount}/${total} ${isRescore ? 'scores' : 'reports'}`
              : data.status === 'cancelled'
                ? 'Cancelled'
                : data.status === 'failed'
                  ? 'Finished with errors'
                  : 'Complete'}
          </span>
          <span className="font-mono">{data.percent?.toFixed?.(0) ?? data.percent}%</span>
        </div>
        <div
          className="h-1.5 overflow-hidden rounded-full bg-[var(--color-surface-3)]"
          role="progressbar"
          aria-valuenow={data.percent}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div
            className="h-full rounded-full bg-[var(--color-accent)] transition-[width] duration-300"
            style={{ width: `${Math.max(2, Math.min(100, data.percent || 0))}%` }}
          />
        </div>
      </div>

      {active && (
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm font-semibold text-[var(--color-text-primary)]">
            {data.current_ticker || '…'}
          </span>
          <span className="text-[11px] text-[var(--color-text-muted)]">
            {data.current_ticker
              ? `${isRescore ? 'rescore' : 'core report'} · ${(data.current_index ?? 0) + 1} of ${total}`
              : 'Starting…'}
          </span>
        </div>
      )}

      <div className="flex flex-wrap gap-1.5">
        {stages.map((s, i) => {
          const done = active && currentStageIdx > i;
          const current = active && currentStageIdx === i;
          return (
            <span
              key={s.id}
              className={`rounded px-2 py-0.5 text-[11px] font-semibold ${
                current
                  ? 'bg-[var(--color-accent)] text-[var(--color-surface-0)]'
                  : done
                    ? 'bg-[color-mix(in_oklch,var(--color-up)_22%,transparent)] text-[var(--color-up)]'
                    : 'bg-[var(--color-surface-2)] text-[var(--color-text-muted)]'
              }`}
            >
              {s.label}
            </span>
          );
        })}
      </div>

      {(data.completed?.length ?? 0) > 0 && (
        <div className="mt-2 flex max-h-24 flex-wrap gap-1.5 overflow-auto">
          {data.completed.slice(-8).map((c) => (
            <span
              key={c.ticker}
              className="inline-flex items-center gap-1.5 rounded border border-[var(--color-surface-3)] px-1.5 py-0.5 text-[11px]"
            >
              <span className="font-mono">{c.ticker}</span>
              {c.rating && <RatingBadge rating={c.rating} />}
              {c.score != null && <ScoreMeter value={c.score} showLabel />}
            </span>
          ))}
        </div>
      )}

      {(data.errors?.length ?? 0) > 0 && (
        <p className="mt-2 text-[11px] text-[var(--color-down)]">
          {data.errors.length} error(s)
          {data.errors[0] ? ` — ${data.errors[0].ticker}: ${data.errors[0].error.slice(0, 80)}` : ''}
        </p>
      )}
    </Panel>
  );
}
