/** Structured decision card — rating, score, levels, plan, drivers. */
import type { ResearchReport } from '../api/types';
import { ScoreMeter } from './ScoreMeter';

const RATING_COLORS: Record<string, { bg: string; border: string; color: string }> = {
  STRONG_BUY: { bg: 'color-mix(in oklch, var(--color-rating-strong-buy) 18%, var(--color-surface-1))', border: 'color-mix(in oklch, var(--color-rating-strong-buy) 45%, transparent)', color: 'var(--color-rating-strong-buy)' },
  BUY: { bg: 'color-mix(in oklch, var(--color-rating-buy) 16%, var(--color-surface-1))', border: 'color-mix(in oklch, var(--color-rating-buy) 40%, transparent)', color: 'var(--color-rating-buy)' },
  ACCUMULATE: { bg: 'color-mix(in oklch, var(--color-rating-accumulate) 14%, var(--color-surface-1))', border: 'color-mix(in oklch, var(--color-rating-accumulate) 35%, transparent)', color: 'var(--color-rating-accumulate)' },
  HOLD: { bg: 'color-mix(in oklch, var(--color-rating-hold) 14%, var(--color-surface-1))', border: 'color-mix(in oklch, var(--color-rating-hold) 40%, transparent)', color: 'var(--color-rating-hold)' },
  REDUCE: { bg: 'color-mix(in oklch, var(--color-rating-reduce) 14%, var(--color-surface-1))', border: 'color-mix(in oklch, var(--color-rating-reduce) 35%, transparent)', color: 'var(--color-rating-reduce)' },
  SELL: { bg: 'color-mix(in oklch, var(--color-rating-sell) 16%, var(--color-surface-1))', border: 'color-mix(in oklch, var(--color-rating-sell) 40%, transparent)', color: 'var(--color-rating-sell)' },
  STRONG_SELL: { bg: 'color-mix(in oklch, var(--color-rating-strong-sell) 18%, var(--color-surface-1))', border: 'color-mix(in oklch, var(--color-rating-strong-sell) 45%, transparent)', color: 'var(--color-rating-strong-sell)' },
};

function fmtPrice(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '—';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: n % 1 === 0 ? 0 : 2,
  }).format(n);
}

/** Split freeform position plan into readable bullets; drop lines that only restate levels. */
function planBullets(
  note: string | null | undefined,
  levels: { entry?: number | null; stop?: number | null; target?: number | null },
): string[] {
  if (!note?.trim()) return [];
  const chunks = note
    .split(/(?<=[.!;])\s+/)
    .map((s) => s.trim())
    .filter(Boolean);

  const nums = [levels.entry, levels.stop, levels.target]
    .filter((v): v is number => v != null)
    .map(String);

  return chunks.filter((chunk) => {
    // Levels + R:R already shown in metric tiles — drop restated stop/target lines
    if (/^stop at\b/i.test(chunk)) return false;
    if (/^target\b/i.test(chunk) && /\b(upside|reward)/i.test(chunk)) return false;
    if (
      /\bstop at\b/i.test(chunk) &&
      /\bdownside\b/i.test(chunk) &&
      !/\b(size|weight|tranche|scale)\b/i.test(chunk)
    ) {
      return false;
    }
    if (
      /\btarget\b/i.test(chunk) &&
      /\b(upside|reward\s*\/\s*risk)\b/i.test(chunk) &&
      !/\b(size|weight|tranche|scale|initiate|add)\b/i.test(chunk)
    ) {
      return false;
    }
    // Tiny fragments that only mention a level number
    if (chunk.length < 40 && nums.some((n) => chunk.includes(n))) return false;
    return true;
  });
}

function rewardRisk(
  entry: number | null | undefined,
  stop: number | null | undefined,
  target: number | null | undefined,
): { label: string; sub: string } | null {
  if (entry == null || stop == null || target == null) return null;
  const risk = entry - stop;
  const reward = target - entry;
  if (risk === 0) return null;
  const ratio = Math.abs(reward / risk);
  const upside = ((target - entry) / entry) * 100;
  const downside = ((entry - stop) / entry) * 100;
  return {
    label: `${ratio.toFixed(1)} : 1`,
    sub: `${upside >= 0 ? '+' : ''}${upside.toFixed(0)}% / ${downside >= 0 ? '−' : '+'}${Math.abs(downside).toFixed(0)}%`,
  };
}

export function DecisionBrief({ report }: { report: ResearchReport }) {
  const { rating } = report;
  if (!rating?.rating) return null;

  const c = RATING_COLORS[rating.rating] || RATING_COLORS.HOLD;
  const levels = report.entry_levels;
  const score = rating.score ?? 0;
  const rr = rewardRisk(levels?.entry, levels?.stop, levels?.target);
  const bullets = planBullets(levels?.position_note, {
    entry: levels?.entry,
    stop: levels?.stop,
    target: levels?.target,
  });
  const hasLevels =
    levels &&
    (levels.entry != null || levels.stop != null || levels.target != null || bullets.length > 0);

  return (
    <section className="decision-brief">
      <p className="decision-brief__disclaimer">Research report — not financial advice</p>

      <div className="decision-brief__hero">
        <div
          className={`decision-brief__rating${report.report_type === 'deep' ? ' decision-brief__rating--deep' : ''}`}
          style={{ background: c.bg, borderColor: c.border, color: c.color }}
          title={report.report_type === 'deep' ? 'Deep report' : report.report_type === 'core' ? 'Core report' : undefined}
        >
          {rating.rating.replace(/_/g, ' ')}
        </div>
        <div className="decision-brief__hero-copy">
          <p className="decision-brief__posture">
            {rating.posture || 'No strong edge to add or cut'}
          </p>
          <div className="decision-brief__score-block">
            <span className="decision-brief__label">AI score (−100 sell → +100 buy)</span>
            <ScoreMeter value={score} size="md" reportType={report.report_type} />
          </div>
          {rating.calibration_note && (
            <p className="decision-brief__meta">{rating.calibration_note}</p>
          )}
        </div>
      </div>

      {hasLevels && (
        <div className="decision-brief__levels">
          <div className="decision-brief__metrics">
            {levels?.entry != null && (
              <div className="decision-metric">
                <span className="decision-brief__label">Entry</span>
                <span className="decision-metric__value decision-metric__value--entry">
                  {fmtPrice(levels.entry)}
                </span>
              </div>
            )}
            {levels?.stop != null && (
              <div className="decision-metric">
                <span className="decision-brief__label">Stop</span>
                <span className="decision-metric__value decision-metric__value--stop">
                  {fmtPrice(levels.stop)}
                </span>
              </div>
            )}
            {levels?.target != null && (
              <div className="decision-metric">
                <span className="decision-brief__label">Target</span>
                <span className="decision-metric__value decision-metric__value--target">
                  {fmtPrice(levels.target)}
                </span>
              </div>
            )}
            {rr && (
              <div className="decision-metric">
                <span className="decision-brief__label">Reward / risk</span>
                <span className="decision-metric__value">{rr.label}</span>
                <span className="decision-metric__sub">{rr.sub}</span>
              </div>
            )}
          </div>

          {(bullets.length > 0 || levels?.position_note) && (
            <div className="decision-plan">
              <span className="decision-brief__label">Position plan</span>
              {bullets.length > 1 ? (
                <ul className="decision-plan__list">
                  {bullets.map((b) => (
                    <li key={b}>{b}</li>
                  ))}
                </ul>
              ) : (
                <p className="decision-plan__text">
                  {bullets[0] || levels?.position_note || 'Maintain current position; do not add.'}
                </p>
              )}
            </div>
          )}
        </div>
      )}

      <div className="decision-brief__meta-row">
        <span>
          <strong>{report.ticker}</strong>
        </span>
        {report.live_price != null && (
          <span>
            Live <strong>{fmtPrice(report.live_price)}</strong>
          </span>
        )}
        <span>Generated {new Date(report.created_at).toLocaleDateString()}</span>
      </div>

      {rating.key_drivers.length > 0 && (
        <div className="decision-drivers">
          <span className="decision-brief__label">Key drivers</span>
          <ul className="decision-drivers__list">
            {rating.key_drivers.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
