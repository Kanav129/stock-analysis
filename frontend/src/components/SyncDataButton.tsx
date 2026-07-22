import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type { SyncProgress } from '../api/types';

function formatHkt(iso: string, timezone = 'Asia/Hong_Kong') {
  return `${new Date(iso).toLocaleTimeString('en-HK', {
    timeZone: timezone,
    hour: '2-digit',
    minute: '2-digit',
  })} HKT`;
}

/** Compact trigger; progress lives in SyncProgressTracker. */
export function SyncDataButton({ className = '' }: { className?: string }) {
  const qc = useQueryClient();

  const statusQ = useQuery({
    queryKey: ['sync-status'],
    queryFn: api.getSyncStatus,
    refetchInterval: (q) => {
      const d = q.state.data as SyncProgress | undefined;
      return d?.running ? 2000 : 30_000;
    },
    refetchIntervalInBackground: true,
  });

  const running = Boolean(statusQ.data?.running) || statusQ.data?.status === 'running';

  const mutation = useMutation({
    mutationFn: (force: boolean) => api.syncData(undefined, { force }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sync-status'] });
    },
  });

  const busy = mutation.isPending || running;
  const daily = statusQ.data?.daily;
  const completedToday = Boolean(daily?.already_completed_today);
  const canResume = Boolean(daily?.can_resume);
  const label = busy
    ? 'Sync running…'
    : completedToday
      ? 'Run again'
      : 'Sync news & price data';
  const subtitle = completedToday
    ? `Completed today${daily?.finished_at ? ` · ${formatHkt(daily.finished_at, daily.timezone || 'Asia/Hong_Kong')}` : ''}`
    : canResume
      ? `Resuming · ${daily?.prices_done_count ?? 0} prices done`
      : null;

  return (
    <div className={`flex flex-col items-stretch gap-2 ${className}`}>
      <button
        type="button"
        onClick={() => mutation.mutate(completedToday)}
        disabled={busy}
        className="btn-terminal"
      >
        {label}
      </button>
      {subtitle && <p className="text-xs text-[var(--color-muted)]">{subtitle}</p>}
      {mutation.isError && (
        <p className="text-xs text-[var(--color-down)]">
          {mutation.error instanceof Error ? mutation.error.message : 'Sync failed'}
        </p>
      )}
    </div>
  );
}
