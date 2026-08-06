import { useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
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

function isDeskBusy(snap?: JobsSnapshot | null): boolean {
  if (!snap) return false;
  const sync = snap.sync;
  const syncing = Boolean(sync?.running) || sync?.status === 'running';
  const analysis = snap.analysis;
  const analyzing =
    Boolean(analysis?.running) ||
    analysis?.status === 'running' ||
    analysis?.status === 'pending';
  const queued = Boolean(
    snap.jobs?.some((j) => j.status === 'queued' || j.status === 'running'),
  );
  return syncing || analyzing || queued;
}

/**
 * Sole owner of desk status refetch intervals.
 * Busy: full GET /jobs (sync + jobs + analysis) every POLL_ACTIVE_MS.
 * Idle: lite GET /jobs?lite=1 (skips heavy analysis status) every POLL_IDLE_MS.
 * Fans out into shared query keys; polling pauses when the tab is hidden.
 */
export function useSyncKeepAlive() {
  const qc = useQueryClient();

  const deskQ = useQuery({
    queryKey: ['jobs'],
    queryFn: async () => {
      const prev = qc.getQueryData<JobsSnapshot>(['jobs']);
      // First paint / busy desk → full snapshot. Idle refresh stays skinny.
      const lite = Boolean(prev) && !isDeskBusy(prev);
      return api.getJobs({ lite });
    },
    refetchInterval: (q) => {
      const d = q.state.data as JobsSnapshot | undefined;
      return visiblePollInterval(isDeskBusy(d) ? POLL_ACTIVE_MS : POLL_IDLE_MS);
    },
    refetchIntervalInBackground: false,
    staleTime: POLL_STALE_MS,
  });

  useEffect(() => {
    const snap = deskQ.data;
    if (!snap) return;
    if (snap.sync) {
      qc.setQueryData(['sync-status'], snap.sync);
    } else {
      // Keep subscribers from seeing stale "running" when snapshot omits idle sync
      const prev = qc.getQueryData<SyncProgress>(['sync-status']);
      if (prev?.running || prev?.status === 'running') {
        qc.setQueryData(['sync-status'], {
          ...prev,
          running: false,
          status: prev.status === 'running' ? 'idle' : prev.status,
        });
      }
    }
    // Lite idle polls omit analysis — preserve last full snapshot in cache
    if (snap.analysis) {
      qc.setQueryData(['analysis-status'], snap.analysis as AnalysisProgress);
    }
  }, [deskQ.data, qc]);

  const active = isDeskBusy(deskQ.data);

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
