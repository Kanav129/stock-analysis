import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';

/** Sync IBKR Flex Open Positions into the desk holdings snapshot. */
export function SyncHoldingsButton({ className = '' }: { className?: string }) {
  const qc = useQueryClient();

  const mutation = useMutation({
    mutationFn: () => api.syncHoldings(),
    onSuccess: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['desk-snapshot'] }),
        qc.invalidateQueries({ queryKey: ['holdings'] }),
        qc.invalidateQueries({ queryKey: ['universe'] }),
        qc.invalidateQueries({ queryKey: ['quotes'] }),
        qc.invalidateQueries({ queryKey: ['ratings'] }),
        qc.invalidateQueries({ queryKey: ['watchlist'] }),
      ]);
    },
  });

  const busy = mutation.isPending;
  const saved = mutation.data?.saved;

  return (
    <div className={`flex flex-col items-end gap-1 ${className}`}>
      <button
        type="button"
        onClick={() => mutation.mutate()}
        disabled={busy}
        className="btn-terminal"
        aria-busy={busy || undefined}
      >
        {busy ? 'Syncing holdings…' : 'Sync holdings'}
      </button>
      {mutation.isSuccess && (
        <p className="text-xs text-[var(--color-text-muted)]">
          Imported {saved ?? 0} position{(saved ?? 0) === 1 ? '' : 's'}
          {(mutation.data?.skipped ?? 0) > 0
            ? ` · skipped ${mutation.data?.skipped}`
            : ''}
        </p>
      )}
      {mutation.isError && (
        <p className="max-w-[14rem] text-right text-xs text-[var(--color-down)]">
          {mutation.error instanceof Error
            ? mutation.error.message
            : 'Holdings sync failed'}
        </p>
      )}
    </div>
  );
}
