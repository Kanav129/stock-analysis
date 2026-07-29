import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { DeskRunActions } from '../components/DeskRunActions';
import { JobsPanel } from '../components/JobsPanel';
import { WatchlistList } from '../components/WatchlistList';
import { LoadingState } from '../components/LoadingSpinner';

export function WatchlistPage() {
  const [ticker, setTicker] = useState('');
  const [notes, setNotes] = useState('');
  const qc = useQueryClient();

  const watchlistQ = useQuery({ queryKey: ['watchlist'], queryFn: api.getWatchlist });

  const add = useMutation({
    mutationFn: () => api.addWatchlist(ticker.toUpperCase(), notes || undefined),
    onSuccess: () => {
      setTicker('');
      setNotes('');
      qc.invalidateQueries({ queryKey: ['watchlist'] });
    },
  });

  const items = watchlistQ.data?.items ?? [];

  return (
    <div className="flex flex-col gap-8 animate-fade-up">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="font-display text-2xl font-semibold">Watchlist</h2>
          <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
            Add tickers you want to track. They will be included in daily scraping and AI analysis.
          </p>
        </div>
        <DeskRunActions showAnalysis={false} />
      </div>

      <JobsPanel />

      <form
        className="flex flex-wrap gap-3 rounded-lg bg-[var(--color-surface-1)] p-6"
        onSubmit={(e) => {
          e.preventDefault();
          if (ticker.trim()) add.mutate();
        }}
      >
        <input
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          placeholder="Ticker (e.g. AAPL)"
          className="rounded-md bg-[var(--color-surface-2)] px-3 py-2 font-mono text-sm outline-none ring-[var(--color-accent)] focus:ring-2"
        />
        <input
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Notes (optional)"
          className="min-w-[200px] flex-1 rounded-md bg-[var(--color-surface-2)] px-3 py-2 text-sm outline-none ring-[var(--color-accent)] focus:ring-2"
        />
        <button
          type="submit"
          disabled={!ticker.trim() || add.isPending}
          className="rounded-md bg-[var(--color-accent)] px-4 py-2 text-sm font-medium text-[var(--color-surface-0)] disabled:opacity-50"
        >
          Add
        </button>
      </form>

      <div className="rounded-lg bg-[var(--color-surface-1)]">
        {watchlistQ.isLoading ? (
          <LoadingState label="Loading watchlist…" minHeight="8rem" />
        ) : items.length ? (
          <WatchlistList items={items} />
        ) : (
          <p className="p-6 text-sm text-[var(--color-text-muted)]">No watchlist items yet.</p>
        )}
      </div>
    </div>
  );
}
