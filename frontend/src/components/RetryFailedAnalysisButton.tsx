import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';

export function RetryFailedAnalysisButton() {
  const qc = useQueryClient();
  const ratingsQ = useQuery({
    queryKey: ['ratings'],
    queryFn: () => api.getRatings(),
    staleTime: 5_000,
  });
  const statusQ = useQuery({
    queryKey: ['analysis-status'],
    queryFn: api.getAnalysisStatus,
    staleTime: 5_000,
  });
  const jobsQ = useQuery({
    queryKey: ['jobs'],
    queryFn: () => api.getJobs(),
    staleTime: 5_000,
  });

  const mutation = useMutation({
    mutationFn: api.retryFailedAnalysis,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['analysis-status'] });
      void qc.invalidateQueries({ queryKey: ['jobs'] });
      void qc.invalidateQueries({ queryKey: ['ratings'] });
    },
  });

  const failedCount = ratingsQ.data?.ratings.filter(
    (rating) => rating.analysis_failed,
  ).length;
  const analysisJobBusy = Boolean(
    jobsQ.data?.jobs?.some(
      (job) =>
        (job.job_type === 'core_analysis' ||
          job.job_type === 'deep_dive' ||
          job.job_type === 'rescore') &&
        (job.status === 'queued' || job.status === 'running'),
    ),
  );
  const busy =
    Boolean(statusQ.data?.running) || analysisJobBusy || mutation.isPending;
  const disabled = busy || failedCount === undefined || failedCount === 0;
  const label =
    failedCount === undefined ? 'Retry failed' : `Retry failed (${failedCount})`;

  return (
    <div className="flex flex-col items-stretch gap-1">
      <button
        type="button"
        onClick={() => mutation.mutate()}
        disabled={disabled}
        className="btn-desk-run"
        aria-busy={busy || undefined}
      >
        <span className="btn-desk-run__label">{label}</span>
      </button>
      {mutation.isError ? (
        <p className="text-xs text-[var(--color-down)]">
          {mutation.error instanceof Error
            ? mutation.error.message
            : 'Retry failed analyses failed'}
        </p>
      ) : null}
    </div>
  );
}
