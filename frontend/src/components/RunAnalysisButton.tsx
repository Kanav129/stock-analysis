import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';

function formatHkt(iso: string, timezone = 'Asia/Hong_Kong') {
  return `${new Date(iso).toLocaleTimeString('en-HK', {
    timeZone: timezone,
    hour: '2-digit',
    minute: '2-digit',
  })} HKT`;
}

export function RunAnalysisButton() {
  const qc = useQueryClient();
  const statusQ = useQuery({
    queryKey: ['analysis-status'],
    queryFn: api.getAnalysisStatus,
    refetchInterval: (q) => (q.state.data?.running ? 800 : false),
    refetchIntervalInBackground: true,
  });

  const mutation = useMutation({
    mutationFn: (force: boolean) => api.runAnalysis(undefined, { force }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['analysis-status'] });
    },
  });

  const busy = Boolean(statusQ.data?.running) || mutation.isPending;
  const daily = statusQ.data?.daily;
  const completedToday = Boolean(daily?.already_completed_today);
  const canResume = Boolean(daily?.can_resume);
  const label = busy ? 'Reports running…' : completedToday ? 'Run again' : 'Run analysis now';
  const subtitle = completedToday
    ? `Completed today${daily?.finished_at ? ` · ${formatHkt(daily.finished_at, daily.timezone || 'Asia/Hong_Kong')}` : ''}`
    : canResume
      ? `Resuming · ${daily?.completed_count ?? 0} completed`
      : null;

  return (
    <div className="flex flex-col items-stretch gap-2">
      <button
        type="button"
        onClick={() => mutation.mutate(completedToday)}
        disabled={busy}
        className="btn-terminal btn-terminal--accent"
        style={{
          background: busy ? 'var(--color-surface-2)' : undefined,
          opacity: busy ? 0.7 : 1,
        }}
      >
        {label}
      </button>
      {subtitle && <p className="text-xs text-[var(--color-muted)]">{subtitle}</p>}
    </div>
  );
}
