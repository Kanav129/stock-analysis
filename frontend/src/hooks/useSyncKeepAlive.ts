import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { AnalysisProgress, SyncProgress } from '../api/types';

/** Render free dynos sleep after ~15m without HTTP; keep a heartbeat while long jobs run. */
const KEEPALIVE_MS = 10 * 60 * 1000;

function isActiveJob(sync?: SyncProgress, analysis?: AnalysisProgress): boolean {
  const syncing = Boolean(sync?.running) || sync?.status === 'running';
  const analyzing =
    Boolean(analysis?.running) ||
    analysis?.status === 'running' ||
    analysis?.status === 'pending';
  return syncing || analyzing;
}

/**
 * While sync or analysis is running, ping /health every ~10 minutes (and once on
 * start) so the free Render dyno does not spin down. Also enables status refetch
 * while the tab is in the background (TanStack Query pauses by default).
 */
export function useSyncKeepAlive() {
  const syncQ = useQuery({
    queryKey: ['sync-status'],
    queryFn: api.getSyncStatus,
    refetchInterval: (q) => {
      const d = q.state.data as SyncProgress | undefined;
      return d?.running || d?.status === 'running' ? 5_000 : 30_000;
    },
    refetchIntervalInBackground: true,
    staleTime: 2_000,
  });

  const analysisQ = useQuery({
    queryKey: ['analysis-status'],
    queryFn: api.getAnalysisStatus,
    refetchInterval: (q) => {
      const d = q.state.data as AnalysisProgress | undefined;
      return d?.running || d?.status === 'running' || d?.status === 'pending'
        ? 5_000
        : 30_000;
    },
    refetchIntervalInBackground: true,
    staleTime: 2_000,
  });

  const active = isActiveJob(syncQ.data, analysisQ.data);

  useEffect(() => {
    if (!active) return;

    const beat = () => {
      void api.health().catch(() => {
        /* ignore — next interval retries */
      });
    };

    beat();
    const id = window.setInterval(beat, KEEPALIVE_MS);
    return () => window.clearInterval(id);
  }, [active]);
}
