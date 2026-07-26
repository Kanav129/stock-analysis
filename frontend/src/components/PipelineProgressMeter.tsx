import './pipelineProgress.css';

/** Transform-based progress fill with sheen while active (state, not decoration). */
export function PipelineProgressMeter({
  percent,
  active,
  tone = 'accent',
  label,
}: {
  percent: number;
  active: boolean;
  tone?: 'accent' | 'error' | 'done';
  label: string;
}) {
  const pct = Math.max(0, Math.min(100, Number(percent) || 0));
  const fillScale = Math.max(active ? 0.02 : 0, pct / 100);

  return (
    <div
      className={`pipeline-meter${active ? ' pipeline-meter--active' : ''}`}
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
      aria-busy={active || undefined}
    >
      <div
        className={[
          'pipeline-meter__fill',
          tone === 'error' ? 'pipeline-meter__fill--error' : '',
          tone === 'done' ? 'pipeline-meter__fill--done' : '',
        ]
          .filter(Boolean)
          .join(' ')}
        style={{ transform: `scaleX(${fillScale})` }}
      />
      {active ? <div className="pipeline-meter__sheen" aria-hidden="true" /> : null}
    </div>
  );
}

export function PipelineLiveBadge({ verb }: { verb: string }) {
  return (
    <span className="pipeline-live" aria-live="polite">
      <span className="pipeline-live__dot" aria-hidden="true" />
      <span className="pipeline-live__label">
        <span className="pipeline-ellipsis">{verb}</span>
      </span>
    </span>
  );
}

export function PipelineStageChip({
  label,
  state,
}: {
  label: string;
  state: 'idle' | 'current' | 'done' | 'failed';
}) {
  const mod =
    state === 'current'
      ? ' pipeline-stage-chip--current'
      : state === 'done'
        ? ' pipeline-stage-chip--done'
        : state === 'failed'
          ? ' pipeline-stage-chip--failed'
          : '';
  return <span className={`pipeline-stage-chip${mod}`}>{label}</span>;
}
