import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { Panel } from './Panel';
import {
  PipelineLiveBadge,
  PipelineProgressMeter,
  PipelineStageChip,
} from './PipelineProgressMeter';
import type { SyncProgress } from '../api/types';

const SYNC_STAGES = [
  { id: 'news', label: 'News', verb: 'Pulling news' },
  { id: 'prices', label: 'Prices', verb: 'Extracting prices' },
  { id: 'vectors', label: 'Indexing', verb: 'Indexing' },
];

function humanStageLabel(stage: string | null | undefined, stageLabel: string | null | undefined) {
  if (stage === 'vectors' || stageLabel === 'Vectors') return 'Indexing';
  return stageLabel || stage || 'Working';
}

function stageIndex(stage: string | null | undefined): number {
  if (!stage) return -1;
  return SYNC_STAGES.findIndex((s) => s.id === stage);
}

function activityVerb(stage: string | null | undefined): string {
  const hit = SYNC_STAGES.find((s) => s.id === stage);
  return hit?.verb ?? 'Working';
}

export function SyncProgressTracker() {
  const qc = useQueryClient();
  const [dismissedAt, setDismissedAt] = useState<string | null>(null);

  const statusQ = useQuery({
    queryKey: ['sync-status'],
    queryFn: api.getSyncStatus,
    refetchInterval: (q) => {
      const d = q.state.data as SyncProgress | undefined;
      // Sub-step detail updates often during price ladder work.
      return d?.running || d?.status === 'running' ? 500 : 20_000;
    },
    refetchIntervalInBackground: true,
  });

  const cancelMut = useMutation({
    mutationFn: api.cancelSync,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sync-status'] }),
  });

  const data = statusQ.data;
  const active = Boolean(data?.running) || data?.status === 'running';
  const showDone =
    !active &&
    (data?.status === 'completed' ||
      data?.status === 'error' ||
      data?.status === 'cancelled' ||
      data?.status === 'partial') &&
    data.finished_at &&
    dismissedAt !== data.finished_at;

  useEffect(() => {
    if (!showDone || !data?.finished_at) return;
    const age = Date.now() - new Date(data.finished_at).getTime();
    if (age > 90_000) {
      setDismissedAt(data.finished_at);
      return;
    }
    const t = window.setTimeout(() => setDismissedAt(data.finished_at!), Math.max(0, 90_000 - age));
    return () => window.clearTimeout(t);
  }, [showDone, data?.finished_at]);

  useEffect(() => {
    if (!active && data?.status === 'completed' && data.finished_at) {
      qc.invalidateQueries({ queryKey: ['chart'] });
      qc.invalidateQueries({ queryKey: ['quotes'] });
      qc.invalidateQueries({ queryKey: ['holdings'] });
      qc.invalidateQueries({ queryKey: ['technicals'] });
      qc.invalidateQueries({ queryKey: ['news'] });
      qc.invalidateQueries({ queryKey: ['watchlist'] });
    }
  }, [active, data?.status, data?.finished_at, qc]);

  if (!data || (!active && !showDone)) return null;

  const total = data.total || data.tickers?.length || 0;
  const doneCount = data.completed?.length ?? 0;
  const currentStageIdx = stageIndex(data.stage);
  const percent = Math.max(0, Math.min(100, Number(data.percent) || 0));
  const meterTone =
    data.status === 'error' ? 'error' : !active && data.status === 'completed' ? 'done' : 'accent';

  return (
    <Panel
      title="Sync progress"
      subtitle={data.message || 'Fetching news & prices'}
      dense
      actions={
        active ? (
          <button
            type="button"
            className="btn-terminal"
            disabled={cancelMut.isPending || Boolean(data.message?.toLowerCase().includes('cancel'))}
            onClick={() => cancelMut.mutate()}
          >
            {cancelMut.isPending || data.message?.toLowerCase().includes('cancel')
              ? 'Cancelling…'
              : 'Cancel'}
          </button>
        ) : undefined
      }
    >
      <div className="mb-2">
        <div className="mb-1 flex items-center justify-between gap-2 text-[11px] text-[var(--color-text-muted)]">
          <span className="inline-flex items-center gap-2 font-mono">
            {active ? (
              <>
                <PipelineLiveBadge verb={activityVerb(data.stage)} />
                <span className="text-[var(--color-text-muted)]">
                  {data.stage === 'vectors'
                    ? 'news index'
                    : `${Math.min(doneCount + (data.current_ticker ? 1 : 0), total)}/${total}`}
                </span>
              </>
            ) : data.status === 'cancelled' ? (
              'Cancelled — resume anytime'
            ) : data.status === 'error' ? (
              'Finished with errors'
            ) : data.status === 'partial' ? (
              'Partial'
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
          label="Sync progress"
        />
      </div>

      {active && (
        <div className="mb-2 flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <span
              key={data.current_ticker || data.stage || 'idle'}
              className="pipeline-ticker-swap font-mono text-sm font-semibold text-[var(--color-text-primary)]"
            >
              {data.current_ticker || (data.stage === 'vectors' ? 'News index' : '…')}
            </span>
            <span className="text-[11px] text-[var(--color-text-muted)]">
              {humanStageLabel(data.stage, data.stage_label)}
              {data.current_ticker && total
                ? ` · ${(data.current_index ?? 0) + 1} of ${total}`
                : ''}
            </span>
          </div>
          {data.detail ? (
            <p
              key={data.detail}
              className="pipeline-ticker-swap font-mono text-[11px] tabular-nums text-[var(--color-accent)]"
              aria-live="polite"
            >
              {data.detail}
            </p>
          ) : null}
        </div>
      )}

      <div className="flex flex-wrap gap-1.5">
        {SYNC_STAGES.map((s, i) => {
          const done = (active && currentStageIdx > i) || (!active && data.status === 'completed');
          const current = active && currentStageIdx === i;
          const failed = !active && data.status === 'error' && currentStageIdx === i;
          return (
            <PipelineStageChip
              key={s.id}
              label={s.label}
              state={failed ? 'failed' : current ? 'current' : done ? 'done' : 'idle'}
            />
          );
        })}
      </div>

      {(data.completed?.length ?? 0) > 0 && (
        <div className="mt-2 flex max-h-20 flex-wrap gap-1 overflow-auto">
          {data.completed.slice(-16).map((ticker, i) => (
            <span
              key={`${ticker}-${i}`}
              className="pipeline-done-chip rounded border border-[var(--color-surface-3)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--color-text-secondary)]"
              style={{ animationDelay: `${Math.min(i, 8) * 30}ms` }}
            >
              {ticker}
            </span>
          ))}
        </div>
      )}

      {(data.errors?.length ?? 0) > 0 && (
        <p className="mt-2 text-[11px] text-[var(--color-down)]">
          {data.errors.length} error(s)
          {data.errors[0]
            ? ` — ${data.errors[0].ticker}: ${String(data.errors[0].error).slice(0, 80)}`
            : ''}
        </p>
      )}
    </Panel>
  );
}
