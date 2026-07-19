import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';

export function RunAnalysisButton() {
  const qc = useQueryClient();
  const statusQ = useQuery({
    queryKey: ['analysis-status'],
    queryFn: api.getAnalysisStatus,
    refetchInterval: (q) => (q.state.data?.running ? 800 : false),
  });

  const mutation = useMutation({
    mutationFn: () => api.runAnalysis(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['analysis-status'] });
    },
  });

  const running = statusQ.data?.running || mutation.isPending;

  return (
    <button
      type="button"
      onClick={() => mutation.mutate()}
      disabled={running}
      className="btn-terminal btn-terminal--accent"
      style={{
        background: running ? 'var(--color-surface-2)' : undefined,
        opacity: running ? 0.7 : 1,
      }}
    >
      {running ? 'Reports running…' : 'Run analysis now'}
    </button>
  );
}
