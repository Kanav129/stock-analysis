import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';

export function SyncDataButton({ className = '' }: { className?: string }) {
  const qc = useQueryClient();
  const [tracking, setTracking] = useState(false);

  const statusQ = useQuery({
    queryKey: ['sync-status'],
    queryFn: api.getSyncStatus,
    refetchInterval: tracking ? 3_000 : 30_000,
    staleTime: 2_000,
  });

  const running = Boolean(statusQ.data?.running) || statusQ.data?.status === 'running';

  useEffect(() => {
    if (running) setTracking(true);
    if (tracking && statusQ.data && !running) {
      setTracking(false);
      qc.invalidateQueries({ queryKey: ['chart'] });
      qc.invalidateQueries({ queryKey: ['quotes'] });
      qc.invalidateQueries({ queryKey: ['holdings'] });
      qc.invalidateQueries({ queryKey: ['technicals'] });
      qc.invalidateQueries({ queryKey: ['news'] });
      qc.invalidateQueries({ queryKey: ['watchlist'] });
    }
  }, [running, tracking, statusQ.data, qc]);

  const mutation = useMutation({
    mutationFn: () => api.syncData(),
    onSuccess: () => {
      setTracking(true);
      qc.invalidateQueries({ queryKey: ['sync-status'] });
    },
  });

  const busy = mutation.isPending || running;
  const message = running
    ? statusQ.data?.message || 'Syncing news & prices…'
    : mutation.data?.message;

  return (
    <div className={`flex flex-col items-stretch gap-2 ${className}`}>
      <button
        type="button"
        onClick={() => mutation.mutate()}
        disabled={busy}
        className="btn-terminal"
      >
        {busy ? 'Syncing news & prices…' : 'Sync news & price data'}
      </button>
      {message && (
        <p className={`text-xs ${running || mutation.data?.started ? 'text-[var(--color-up)]' : 'text-[var(--color-text-muted)]'}`}>
          {message}
        </p>
      )}
      {mutation.isError && (
        <p className="text-xs text-[var(--color-down)]">
          {mutation.error instanceof Error ? mutation.error.message : 'Sync failed'}
        </p>
      )}
    </div>
  );
}
