import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type { SyncProgress } from '../api/types';

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
  });

  const running = Boolean(statusQ.data?.running) || statusQ.data?.status === 'running';

  const mutation = useMutation({
    mutationFn: () => api.syncData(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sync-status'] });
    },
  });

  const busy = mutation.isPending || running;

  return (
    <div className={`flex flex-col items-stretch gap-2 ${className}`}>
      <button
        type="button"
        onClick={() => mutation.mutate()}
        disabled={busy}
        className="btn-terminal"
      >
        {busy ? 'Sync running…' : 'Sync news & price data'}
      </button>
      {mutation.isError && (
        <p className="text-xs text-[var(--color-down)]">
          {mutation.error instanceof Error ? mutation.error.message : 'Sync failed'}
        </p>
      )}
    </div>
  );
}
