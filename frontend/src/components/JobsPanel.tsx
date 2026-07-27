import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { Panel } from './Panel';
import {
  PipelineLiveBadge,
  PipelineProgressMeter,
} from './PipelineProgressMeter';
import type { DeskJob, JobsSnapshot, SyncProgress } from '../api/types';
import './jobsPanel.css';

function jobTypeLabel(jobType: string): string {
  if (jobType === 'deep_dive') return 'Deep dive';
  if (jobType === 'rescore') return 'Rescore';
  return 'Analysis';
}

function jobHasActivity(data?: JobsSnapshot): boolean {
  if (!data) return false;
  const sync = data.sync;
  const syncing = Boolean(sync?.running) || sync?.status === 'running';
  const llm = data.jobs.some((j) => j.status === 'queued' || j.status === 'running');
  return syncing || llm;
}

export function JobsPanel() {
  const qc = useQueryClient();
  const [dismissedSyncAt, setDismissedSyncAt] = useState<string | null>(null);

  const jobsQ = useQuery({
    queryKey: ['jobs'],
    queryFn: api.getJobs,
    refetchInterval: (q) => (jobHasActivity(q.state.data) ? 800 : 15_000),
    refetchIntervalInBackground: true,
  });

  const cancelJobMut = useMutation({
    mutationFn: (id: string) => api.cancelJob(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] });
      qc.invalidateQueries({ queryKey: ['analysis-status'] });
    },
  });

  const cancelAllMut = useMutation({
    mutationFn: api.cancelAllJobs,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] });
      qc.invalidateQueries({ queryKey: ['analysis-status'] });
    },
  });

  const cancelSyncMut = useMutation({
    mutationFn: api.cancelSync,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] });
      qc.invalidateQueries({ queryKey: ['sync-status'] });
    },
  });

  const data = jobsQ.data;
  const sync = data?.sync ?? null;
  const syncActive = Boolean(sync?.running) || sync?.status === 'running';
  const syncDone =
    !syncActive &&
    sync &&
    (sync.status === 'completed' ||
      sync.status === 'error' ||
      sync.status === 'cancelled' ||
      sync.status === 'partial') &&
    sync.finished_at &&
    dismissedSyncAt !== sync.finished_at;

  useEffect(() => {
    if (!syncDone || !sync?.finished_at) return;
    const age = Date.now() - new Date(sync.finished_at).getTime();
    if (age > 90_000) {
      setDismissedSyncAt(sync.finished_at);
      return;
    }
    const t = window.setTimeout(
      () => setDismissedSyncAt(sync.finished_at!),
      Math.max(0, 90_000 - age),
    );
    return () => window.clearTimeout(t);
  }, [syncDone, sync?.finished_at]);

  useEffect(() => {
    if (!syncActive && sync?.status === 'completed' && sync.finished_at) {
      qc.invalidateQueries({ queryKey: ['chart'] });
      qc.invalidateQueries({ queryKey: ['quotes'] });
      qc.invalidateQueries({ queryKey: ['holdings'] });
      qc.invalidateQueries({ queryKey: ['technicals'] });
      qc.invalidateQueries({ queryKey: ['news'] });
      qc.invalidateQueries({ queryKey: ['watchlist'] });
      qc.invalidateQueries({ queryKey: ['ratings'] });
    }
  }, [syncActive, sync?.status, sync?.finished_at, qc]);

  useEffect(() => {
    const doneJobs = data?.jobs.filter((j) => j.status === 'done') ?? [];
    if (doneJobs.length) {
      qc.invalidateQueries({ queryKey: ['ratings'] });
      qc.invalidateQueries({ queryKey: ['report'] });
      qc.invalidateQueries({ queryKey: ['analysis-status'] });
    }
  }, [data?.jobs, qc]);

  const running = data?.jobs.filter((j) => j.status === 'running') ?? [];
  const queued = data?.jobs.filter((j) => j.status === 'queued') ?? [];
  const recent = (data?.jobs ?? []).filter((j) =>
    ['done', 'failed', 'cancelled'].includes(j.status),
  );
  const limits = data?.limits;
  const llmActive = running.length > 0 || queued.length > 0;
  const showPanel = syncActive || syncDone || llmActive || recent.length > 0;

  if (!showPanel) return null;

  const subtitleParts: string[] = [];
  if (limits) {
    subtitleParts.push(`LLM ${limits.running}/${limits.max_concurrent} running`);
    if (limits.queued) subtitleParts.push(`${limits.queued} queued`);
  }
  if (syncActive) subtitleParts.push('sync active');

  return (
    <Panel
      title="Jobs"
      subtitle={subtitleParts.join(' · ') || 'Desk activity'}
      dense
      actions={
        llmActive ? (
          <button
            type="button"
            className="btn-ghost"
            disabled={cancelAllMut.isPending}
            onClick={() => cancelAllMut.mutate()}
          >
            Cancel all LLM
          </button>
        ) : null
      }
    >
      {(syncActive || syncDone) && sync ? <SyncJobRow sync={sync} onCancel={() => cancelSyncMut.mutate()} cancelling={cancelSyncMut.isPending} /> : null}

      {running.map((job) => (
        <LlmJobRow
          key={job.id}
          job={job}
          onCancel={() => cancelJobMut.mutate(job.id)}
          cancelling={cancelJobMut.isPending}
        />
      ))}

      {queued.length > 0 ? (
        <div className="jobs-queue">
          <div className="jobs-queue__label">Queued</div>
          {queued.map((job, i) => (
            <div key={job.id} className="jobs-queue__row">
              <span className="jobs-queue__pos">#{i + 1}</span>
              <Link to={`/stock/${job.ticker}`} className="jobs-queue__ticker">
                {job.ticker}
              </Link>
              <span className="jobs-queue__type">{jobTypeLabel(job.job_type)}</span>
              <button
                type="button"
                className="btn-ghost jobs-queue__remove"
                disabled={cancelJobMut.isPending}
                onClick={() => cancelJobMut.mutate(job.id)}
              >
                Remove
              </button>
            </div>
          ))}
        </div>
      ) : null}

      {!llmActive &&
        recent.slice(0, 4).map((job) => (
          <div key={job.id} className="jobs-recent">
            <Link to={`/stock/${job.ticker}`}>{job.ticker}</Link>
            <span>
              {jobTypeLabel(job.job_type)} · {job.status}
            </span>
          </div>
        ))}
    </Panel>
  );
}

function SyncJobRow({
  sync,
  onCancel,
  cancelling,
}: {
  sync: SyncProgress;
  onCancel: () => void;
  cancelling: boolean;
}) {
  const active = Boolean(sync.running) || sync.status === 'running';
  const percent = Math.max(0, Math.min(100, Number(sync.percent) || 0));
  return (
    <div className="jobs-item jobs-item--sync">
      <div className="jobs-item__head">
        <strong>Sync</strong>
        {active ? <PipelineLiveBadge verb="Syncing" /> : null}
        {active ? (
          <button type="button" className="btn-ghost" disabled={cancelling} onClick={onCancel}>
            Cancel
          </button>
        ) : null}
      </div>
      <p className="jobs-item__msg">{sync.detail || sync.message || 'Fetching news & prices'}</p>
      <PipelineProgressMeter
        percent={percent}
        active={active}
        tone={sync.status === 'error' ? 'error' : active ? 'accent' : 'done'}
        label={`Sync ${percent}%`}
      />
    </div>
  );
}

function LlmJobRow({
  job,
  onCancel,
  cancelling,
}: {
  job: DeskJob;
  onCancel: () => void;
  cancelling: boolean;
}) {
  const progress = job.progress || {};
  const percent = Math.max(0, Math.min(100, Number(progress.percent) || 0));
  const label = progress.message || progress.stage_label || `${jobTypeLabel(job.job_type)}…`;
  return (
    <div className="jobs-item">
      <div className="jobs-item__head">
        <Link to={`/stock/${job.ticker}`} className="jobs-item__ticker">
          {job.ticker}
        </Link>
        <span className="jobs-item__badge">{jobTypeLabel(job.job_type)}</span>
        <PipelineLiveBadge verb="Running" />
        <button type="button" className="btn-ghost" disabled={cancelling} onClick={onCancel}>
          {job.cancel_requested ? 'Cancelling…' : 'Cancel'}
        </button>
      </div>
      <p className="jobs-item__msg">{label}</p>
      <PipelineProgressMeter
        percent={percent}
        active
        tone="accent"
        label={`${job.ticker} ${jobTypeLabel(job.job_type)} ${percent}%`}
      />
    </div>
  );
}
