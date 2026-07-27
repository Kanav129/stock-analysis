import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { AnalysisProgress, JobsSnapshot, SyncProgress } from '../api/types';

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
 * While sync, analysis, or queued LLM jobs are active, ping /health every ~10 minutes
 * so the free Render dyno does not spin down.
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

  const jobsQ = useQuery({
    queryKey: ['jobs'],
    queryFn: api.getJobs,
    refetchInterval: (q) => {
      const d = q.state.data as JobsSnapshot | undefined;
      const busy =
        Boolean(d?.jobs?.some((j) => j.status === 'queued' || j.status === 'running')) ||
        Boolean(d?.sync?.running);
      return busy ? 5_000 : 30_000;
    },
    refetchIntervalInBackground: true,
    staleTime: 2_000,
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
