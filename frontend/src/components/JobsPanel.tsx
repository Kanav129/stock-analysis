import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { Panel } from './Panel';
import {
  PipelineLiveBadge,
  PipelineProgressMeter,
} from './PipelineProgressMeter';
import type { DeskJob, SyncProgress } from '../api/types';
import './jobsPanel.css';

function jobTypeLabel(jobType: string): string {
  if (jobType === 'deep_dive') return 'Deep dive';
  if (jobType === 'rescore') return 'Rescore';
  return 'Analysis';
}

const CORE_ANALYSIS_STAGES = [
  'gather_prices',
  'gather_fundamentals',
  'gather_news',
  'gather_sentiment',
  'synthesize_decision',
  'persist',
] as const;

const RESCORE_STAGES = ['synthesize_decision', 'persist'] as const;

function jobStageOrder(jobType: string): readonly string[] | null {
  if (jobType === 'core_analysis') return CORE_ANALYSIS_STAGES;
  if (jobType === 'rescore') return RESCORE_STAGES;
  return null;
}

function jobStepIndex(
  jobType: string,
  stage: string | null | undefined,
): { current: number; total: number } | null {
  const order = jobStageOrder(jobType);
  if (!order || !stage) return null;
  const idx = order.indexOf(stage);
  if (idx < 0) return null;
  return { current: idx + 1, total: order.length };
}

function stripTickerFromProgressText(text: string, ticker: string): string {
  const escaped = ticker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return text
    .replace(new RegExp(`^${escaped}\\s*[:·]\\s*`, 'i'), '')
    .replace(/\s*…$/, '')
    .trim();
}

function runningJobStatus(job: DeskJob): { step: string | null; label: string } {
  const progress = job.progress || {};
  const stepInfo = jobStepIndex(job.job_type, progress.stage);
  const step = stepInfo ? `${stepInfo.current}/${stepInfo.total}` : null;

  const stageLabel = progress.stage_label?.trim();
  if (stageLabel) {
    return { step, label: stageLabel };
  }

  const rawMessage = progress.message?.trim();
  if (rawMessage) {
    const cleaned = stripTickerFromProgressText(rawMessage, job.ticker);
    if (cleaned) return { step, label: cleaned };
  }

  return { step, label: jobTypeLabel(job.job_type) };
}

export function JobsPanel() {
  const qc = useQueryClient();
  const [dismissedSyncAt, setDismissedSyncAt] = useState<string | null>(null);
  const wasSyncActive = useRef(false);
  const seenDoneIds = useRef<Set<string>>(new Set());
  const doneSeeded = useRef(false);

  // Polling owned by useSyncKeepAlive — subscribe only (full snapshot on demand).
  const jobsQ = useQuery({
    queryKey: ['jobs'],
    queryFn: () => api.getJobs(),
    staleTime: 5_000,
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

  // Invalidate price/news caches only when a sync run transitions to completed
  // (manual Sync Data), not on every jobs poll while last status is completed.
  useEffect(() => {
    if (
      wasSyncActive.current &&
      !syncActive &&
      sync?.status === 'completed' &&
      sync.finished_at
    ) {
      void Promise.all([
        qc.invalidateQueries({ queryKey: ['desk-snapshot'] }),
        qc.invalidateQueries({ queryKey: ['chart'] }),
        qc.invalidateQueries({ queryKey: ['quotes'] }),
        qc.invalidateQueries({ queryKey: ['holdings'] }),
        qc.invalidateQueries({ queryKey: ['technicals'] }),
        qc.invalidateQueries({ queryKey: ['news'] }),
        qc.invalidateQueries({ queryKey: ['watchlist'] }),
        qc.invalidateQueries({ queryKey: ['ratings'] }),
      ]);
    }
    wasSyncActive.current = syncActive;
  }, [syncActive, sync?.status, sync?.finished_at, qc]);

  // Invalidate ratings only for jobs that newly reach done — seed historical done ids.
  useEffect(() => {
    // Wait for the first jobs snapshot so we don't treat historical done as new.
    if (!data?.jobs) return;
    const jobs = data.jobs;
    if (!doneSeeded.current) {
      for (const j of jobs) {
        if (j.status === 'done') seenDoneIds.current.add(j.id);
      }
      doneSeeded.current = true;
      return;
    }
    const newlyDone = jobs.filter(
      (j) => j.status === 'done' && !seenDoneIds.current.has(j.id),
    );
    if (!newlyDone.length) return;
    for (const j of newlyDone) seenDoneIds.current.add(j.id);
    void Promise.all([
      qc.invalidateQueries({ queryKey: ['desk-snapshot'] }),
      qc.invalidateQueries({ queryKey: ['ratings'] }),
      qc.invalidateQueries({ queryKey: ['report'] }),
      qc.invalidateQueries({ queryKey: ['analysis-status'] }),
    ]);
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
            className="btn-terminal btn-terminal--danger"
            disabled={cancelAllMut.isPending}
            onClick={() => cancelAllMut.mutate()}
          >
            {cancelAllMut.isPending ? 'Cancelling…' : 'Cancel all LLM'}
          </button>
        ) : null
      }
    >
      {(syncActive || syncDone) && sync ? <SyncJobRow sync={sync} onCancel={() => cancelSyncMut.mutate()} cancelling={cancelSyncMut.isPending} /> : null}

      {running.length > 0 ? (
        <div className="jobs-running">
          {running.map((job) => (
            <LlmJobRow
              key={job.id}
              job={job}
              onCancel={() => cancelJobMut.mutate(job.id)}
              cancelling={cancelJobMut.isPending}
            />
          ))}
        </div>
      ) : null}

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
                className="btn-ghost btn-ghost--danger jobs-queue__remove"
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
          <button
            type="button"
            className="btn-ghost btn-ghost--danger jobs-item__cancel"
            disabled={cancelling}
            onClick={onCancel}
          >
            {cancelling ? 'Cancelling…' : 'Cancel'}
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
  const { step, label } = runningJobStatus(job);
  const statusLabel = step ? `Step ${step} · ${label}` : label;
  return (
    <div className="jobs-item jobs-item--running">
      <Link to={`/stock/${job.ticker}`} className="jobs-item__ticker">
        {job.ticker}
      </Link>
      <span className="jobs-item__badge">{jobTypeLabel(job.job_type)}</span>
      <p className="jobs-item__status">
        <span className="jobs-item__live-dot" aria-hidden="true" />
        {step ? <span className="jobs-item__step">{step}</span> : null}
        <span className="jobs-item__stage">{label}</span>
      </p>
      <div className="jobs-item__track">
        <PipelineProgressMeter
          percent={percent}
          active
          tone="accent"
          size="compact"
          label={`${job.ticker} ${jobTypeLabel(job.job_type)} ${percent}% — ${statusLabel}`}
        />
        <span className="jobs-item__pct">{percent}%</span>
      </div>
      <button
        type="button"
        className="btn-ghost btn-ghost--danger jobs-item__cancel"
        disabled={cancelling}
        onClick={onCancel}
      >
        {job.cancel_requested || cancelling ? 'Cancelling…' : 'Cancel'}
      </button>
    </div>
  );
}
