import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { getDeskRunGate } from './deskRunGate';

/** Pill trigger with inline Done / Resume gate badge. */
export function RunAnalysisButton() {
  const qc = useQueryClient();
  // Polling owned by useSyncKeepAlive — subscribe only.
  const statusQ = useQuery({
    queryKey: ['analysis-status'],
    queryFn: api.getAnalysisStatus,
    staleTime: 5_000,
  });

  const mutation = useMutation({
    mutationFn: (force: boolean) => api.runAnalysis(undefined, { force }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['analysis-status'] });
      qc.invalidateQueries({ queryKey: ['jobs'] });
    },
  });

  const jobsQ = useQuery({
    queryKey: ['jobs'],
    queryFn: () => api.getJobs(),
    staleTime: 5_000,
  });

  const llmBusy = Boolean(
    jobsQ.data?.jobs?.some(
      (j) =>
        (j.job_type === 'core_analysis' || j.job_type === 'rescore') &&
        (j.status === 'queued' || j.status === 'running'),
    ),
  );
  const busy = Boolean(statusQ.data?.running) || mutation.isPending || llmBusy;
  const daily = statusQ.data?.daily;
  const completedToday = Boolean(daily?.already_completed_today);
  const canResume = Boolean(daily?.can_resume);
  const gate = getDeskRunGate('analysis', daily, busy);

  const label = busy
    ? 'Reports running…'
    : completedToday
      ? 'Run again'
      : canResume
        ? 'Resume analysis'
        : 'Run analysis';

  const toneClass =
    gate.tone === 'done'
      ? ' btn-desk-run--done'
      : gate.tone === 'resume'
        ? ' btn-desk-run--resume'
        : '';

  return (
    <button
      type="button"
      onClick={() => mutation.mutate(completedToday)}
      disabled={busy}
      className={`btn-desk-run btn-desk-run--accent${toneClass}`}
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
  );
}
