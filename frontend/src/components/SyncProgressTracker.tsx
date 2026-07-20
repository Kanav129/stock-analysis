import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { Panel } from './Panel';
import type { SyncProgress } from '../api/types';

const SYNC_STAGES = [
  { id: 'news', label: 'News' },
  { id: 'prices', label: 'Prices' },
  { id: 'vectors', label: 'Vectors' },
];

function stageIndex(stage: string | null | undefined): number {
  if (!stage) return -1;
  return SYNC_STAGES.findIndex((s) => s.id === stage);
}

export function SyncProgressTracker() {
  const qc = useQueryClient();
  const [dismissedAt, setDismissedAt] = useState<string | null>(null);

  const statusQ = useQuery({
    queryKey: ['sync-status'],
    queryFn: api.getSyncStatus,
    refetchInterval: (q) => {
      const d = q.state.data as SyncProgress | undefined;
      return d?.running || d?.status === 'running' ? 1000 : 20_000;
    },
  });

  const data = statusQ.data;
  const active = Boolean(data?.running) || data?.status === 'running';
  const showDone =
    !active &&
    (data?.status === 'completed' || data?.status === 'error') &&
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

  return (
    <Panel
      title="Sync progress"
      subtitle={data.message || 'Fetching news & prices'}
      dense
    >
      <div className="mb-2">
        <div className="mb-1 flex items-center justify-between gap-2 text-[11px] text-[var(--color-text-muted)]">
          <span className="font-mono">
            {active
              ? data.stage === 'vectors'
                ? 'Indexing vectors'
                : `${Math.min(doneCount + (data.current_ticker ? 1 : 0), total)}/${total} tickers`
              : data.status === 'error'
                ? 'Finished with errors'
                : 'Complete'}
          </span>
          <span className="font-mono">{percent.toFixed(0)}%</span>
        </div>
        <div
          className="h-1.5 overflow-hidden rounded-full bg-[var(--color-surface-3)]"
          role="progressbar"
          aria-valuenow={percent}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Sync progress"
        >
          <div
            className={`h-full rounded-full transition-[width] duration-300 ${
              data.status === 'error' ? 'bg-[var(--color-down)]' : 'bg-[var(--color-accent)]'
            }`}
            style={{ width: `${Math.max(active ? 2 : 0, percent)}%` }}
          />
        </div>
      </div>

      {active && (
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm font-semibold text-[var(--color-text-primary)]">
            {data.current_ticker || (data.stage === 'vectors' ? 'Chroma' : '…')}
          </span>
          <span className="text-[11px] text-[var(--color-text-muted)]">
            {data.stage_label || data.stage || 'Working'}
            {data.current_ticker && total
              ? ` · ${(data.current_index ?? 0) + 1} of ${total}`
              : ''}
          </span>
        </div>
      )}

      <div className="flex flex-wrap gap-1.5">
        {SYNC_STAGES.map((s, i) => {
          const done = (active && currentStageIdx > i) || (!active && data.status === 'completed');
          const current = active && currentStageIdx === i;
          const failed = !active && data.status === 'error' && currentStageIdx === i;
          return (
            <span
              key={s.id}
              className={`rounded px-2 py-0.5 text-[11px] font-semibold ${
                failed
                  ? 'bg-[color-mix(in_oklch,var(--color-down)_22%,transparent)] text-[var(--color-down)]'
                  : current
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
        <div className="mt-2 flex max-h-20 flex-wrap gap-1 overflow-auto">
          {data.completed.slice(-16).map((ticker) => (
            <span
              key={ticker}
              className="rounded border border-[var(--color-surface-3)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--color-text-secondary)]"
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
