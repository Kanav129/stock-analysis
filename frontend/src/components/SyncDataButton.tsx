import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type { SyncProgress } from '../api/types';
import { getDeskRunGate } from './deskRunGate';

/** Pill trigger with inline Done / Resume gate badge. */
export function SyncDataButton({ className = '' }: { className?: string }) {
  const qc = useQueryClient();

  // Polling owned by useSyncKeepAlive — subscribe only.
  const statusQ = useQuery({
    queryKey: ['sync-status'],
    queryFn: api.getSyncStatus,
    staleTime: 5_000,
  });

  const running = Boolean(statusQ.data?.running) || statusQ.data?.status === 'running';

  const mutation = useMutation({
    mutationFn: (force: boolean) => api.syncData(undefined, { force }),
    onMutate: async () => {
      await qc.cancelQueries({ queryKey: ['sync-status'] });
      const prev = qc.getQueryData<SyncProgress>(['sync-status']);
      // Instant UI: progress tracker keys off sync-status.running before POST returns.
      qc.setQueryData<SyncProgress>(['sync-status'], {
        ...(prev ?? {
          tickers: [],
          total: 0,
          current_index: 0,
          current_ticker: null,
          stage: null,
          stage_label: null,
          completed: [],
          errors: [],
          percent: 0,
          started_at: null,
          finished_at: null,
          last_sync: null,
        }),
        running: true,
        status: 'running',
        message: 'Starting sync…',
        finished_at: null,
        percent: prev?.status === 'running' ? (prev.percent ?? 0) : 0,
      });
      return { prev };
    },
    onError: (_err, _force, ctx) => {
      if (ctx?.prev) qc.setQueryData(['sync-status'], ctx.prev);
    },
    onSuccess: (res) => {
      qc.setQueryData<SyncProgress>(['sync-status'], (old) => ({
        ...(old as SyncProgress),
        ...res,
        running: Boolean(res.running) || res.status === 'running',
        status: res.status ?? (res.started === false ? old?.status ?? 'idle' : 'running'),
        message: res.message ?? old?.message ?? null,
      }));
      void qc.invalidateQueries({ queryKey: ['sync-status'] });
    },
  });

  const busy = mutation.isPending || running;
  const daily = statusQ.data?.daily;
  const completedToday = Boolean(daily?.already_completed_today);
  const canResume = Boolean(daily?.can_resume);
  const gate = getDeskRunGate('sync', daily, busy);

  const label = busy
    ? 'Sync running…'
    : completedToday
      ? 'Run again'
      : canResume
        ? 'Resume sync'
        : 'Sync news & prices';

  const toneClass =
    gate.tone === 'done'
      ? ' btn-desk-run--done'
      : gate.tone === 'resume'
        ? ' btn-desk-run--resume'
        : '';

  return (
    <div className={`flex flex-col items-stretch gap-1 ${className}`}>
      <button
        type="button"
        onClick={() => mutation.mutate(completedToday)}
        disabled={busy}
        className={`btn-desk-run${toneClass}`}
        aria-busy={busy || undefined}
      >
        <span className="btn-desk-run__label">{label}</span>
        {gate.badge ? (
          <span
            className={`btn-desk-run__badge btn-desk-run__badge--${gate.tone}`}
            aria-label={gate.badge}
          >
            {gate.badge}
          </span>
        ) : null}
      </button>
      {mutation.isError && (
        <p className="text-xs text-[var(--color-down)]">
          {mutation.error instanceof Error ? mutation.error.message : 'Sync failed'}
        </p>
      )}
    </div>
  );
}
