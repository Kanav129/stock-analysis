import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { Panel } from './Panel';
import { RatingBadge } from './RatingBadge';
import { ScoreMeter } from './ScoreMeter';
import {
  PipelineLiveBadge,
  PipelineProgressMeter,
  PipelineStageChip,
} from './PipelineProgressMeter';
import type { AnalysisProgress } from '../api/types';

const CORE_STAGES = [
  { id: 'gather_prices', label: 'Technicals', verb: 'Reading technicals' },
  { id: 'gather_fundamentals', label: 'Fundamentals', verb: 'Reading fundamentals' },
  { id: 'gather_news', label: 'News', verb: 'Reading news' },
  { id: 'gather_sentiment', label: 'Sentiment', verb: 'Scoring sentiment' },
  { id: 'synthesize_decision', label: 'Decision', verb: 'Synthesizing call' },
  { id: 'persist', label: 'Save', verb: 'Saving report' },
];

const RESCORE_STAGES = [
  { id: 'synthesize_decision', label: 'Decision', verb: 'Rescoring' },
  { id: 'persist', label: 'Save', verb: 'Saving scores' },
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
    refetchIntervalInBackground: true,
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
  const percent = Math.max(0, Math.min(100, Number(data.percent) || 0));
  const verb =
    stages.find((s) => s.id === data.stage)?.verb ?? (isRescore ? 'Rescoring' : 'Analyzing');
  const meterTone =
    data.status === 'failed' ? 'error' : !active && data.status === 'done' ? 'done' : 'accent';

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
          <span className="inline-flex items-center gap-2 font-mono">
            {active ? (
              <>
                <PipelineLiveBadge verb={verb} />
                <span className="text-[var(--color-text-muted)]">
                  {doneCount}/{total} {isRescore ? 'scores' : 'reports'}
                </span>
              </>
            ) : data.status === 'cancelled' ? (
              'Cancelled'
            ) : data.status === 'failed' ? (
              'Finished with errors'
            ) : (
              'Complete'
            )}
          </span>
          <span className="font-mono tabular-nums">{percent.toFixed(0)}%</span>
        </div>
        <PipelineProgressMeter
          percent={percent}
          active={active}
          tone={meterTone}
          label={isRescore ? 'Rescore progress' : 'Analysis progress'}
        />
      </div>

      {active && (
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <span
            key={data.current_ticker || data.stage || 'idle'}
            className="pipeline-ticker-swap font-mono text-sm font-semibold text-[var(--color-text-primary)]"
          >
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
            <PipelineStageChip
              key={s.id}
              label={s.label}
              state={current ? 'current' : done ? 'done' : 'idle'}
            />
          );
        })}
      </div>

      {(data.completed?.length ?? 0) > 0 && (
        <div className="mt-2 flex max-h-24 flex-wrap gap-1.5 overflow-auto">
          {data.completed.slice(-8).map((c, i) => (
            <span
              key={`${c.ticker}-${c.report_id ?? i}`}
              className="pipeline-done-chip inline-flex items-center gap-1.5 rounded border border-[var(--color-surface-3)] px-1.5 py-0.5 text-[11px]"
              style={{ animationDelay: `${Math.min(i, 6) * 30}ms` }}
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
