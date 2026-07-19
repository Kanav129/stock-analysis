import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';

export function SyncDataButton({ className = '' }: { className?: string }) {
  const qc = useQueryClient();
  const mutation = useMutation({
    mutationFn: () => api.syncData(),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['sync-status'] });
      if (data.started) {
        qc.invalidateQueries({ queryKey: ['chart'] });
        qc.invalidateQueries({ queryKey: ['quotes'] });
        qc.invalidateQueries({ queryKey: ['holdings'] });
        qc.invalidateQueries({ queryKey: ['technicals'] });
        qc.invalidateQueries({ queryKey: ['news'] });
        qc.invalidateQueries({ queryKey: ['watchlist'] });
      }
    },
  });

  return (
    <div className={`flex flex-col items-stretch gap-2 ${className}`}>
      <button
        type="button"
        onClick={() => mutation.mutate()}
        disabled={mutation.isPending}
        className="btn-terminal"
      >
        {mutation.isPending ? 'Syncing news & prices…' : 'Sync news & price data'}
      </button>
      {mutation.data?.message && (
        <p className={`text-xs ${mutation.data.started ? 'text-[var(--color-up)]' : 'text-[var(--color-text-muted)]'}`}>
          {mutation.data.message}
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
