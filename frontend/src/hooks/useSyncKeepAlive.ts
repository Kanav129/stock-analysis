import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { AnalysisProgress, JobsSnapshot, SyncProgress } from '../api/types';
import {
  POLL_ACTIVE_MS,
  POLL_IDLE_MS,
  POLL_STALE_MS,
  visiblePollInterval,
} from '../lib/pollInterval';

/** Render free dynos sleep after ~15m without HTTP; keep a heartbeat while long jobs run. */
const KEEPALIVE_MS = 10 * 60 * 1000;

function isActiveJob(
  sync?: SyncProgress,
  analysis?: AnalysisProgress,
  jobs?: JobsSnapshot,
): boolean {
  const syncing = Boolean(sync?.running) || sync?.status === 'running';
  const analyzing =
    Boolean(analysis?.running) ||
    analysis?.status === 'running' ||
    analysis?.status === 'pending';
  const queued =
    Boolean(jobs?.jobs?.some((j) => j.status === 'queued' || j.status === 'running')) ||
    Boolean(jobs?.sync?.running);
  return syncing || analyzing || queued;
}

/**
 * Sole owner of sync / analysis / jobs refetch intervals for the desk.
 * Other components should useQuery the same keys without refetchInterval.
 *
 * - sync: poll while active; slow refresh when idle (cheap in-memory endpoint)
 * - analysis / jobs: poll only while work is active; one fetch on mount when idle
 * - Polling pauses when the tab is hidden
 */
export function useSyncKeepAlive() {
  const syncQ = useQuery({
    queryKey: ['sync-status'],
    queryFn: api.getSyncStatus,
    refetchInterval: (q) => {
      const d = q.state.data as SyncProgress | undefined;
      const busy = Boolean(d?.running) || d?.status === 'running';
      return visiblePollInterval(busy ? POLL_ACTIVE_MS : POLL_IDLE_MS);
    },
    refetchIntervalInBackground: false,
    staleTime: POLL_STALE_MS,
  });

  const analysisQ = useQuery({
    queryKey: ['analysis-status'],
    queryFn: api.getAnalysisStatus,
    refetchInterval: (q) => {
      const d = q.state.data as AnalysisProgress | undefined;
      const busy =
        Boolean(d?.running) ||
        d?.status === 'running' ||
        d?.status === 'pending';
      return visiblePollInterval(busy ? POLL_ACTIVE_MS : false);
    },
    refetchIntervalInBackground: false,
    staleTime: 60_000,
  });

  const jobsQ = useQuery({
    queryKey: ['jobs'],
    queryFn: api.getJobs,
    refetchInterval: (q) => {
      const d = q.state.data as JobsSnapshot | undefined;
      const busy =
        Boolean(d?.jobs?.some((j) => j.status === 'queued' || j.status === 'running')) ||
        Boolean(d?.sync?.running);
      return visiblePollInterval(busy ? POLL_ACTIVE_MS : false);
    },
    refetchIntervalInBackground: false,
    staleTime: POLL_STALE_MS,
  });

  const active = isActiveJob(syncQ.data, analysisQ.data, jobsQ.data);

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
