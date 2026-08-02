import type { ReportType } from '../api/types';
import { isDeepReport } from '../lib/reportDepth';

/** AI score −100 (sell) … +100 (buy) with red→green gradient track. */

function clampScore(value: number): number {
  return Math.max(-100, Math.min(100, value));
}

function formatScore(value: number): string {
  const n = clampScore(value);
  return n > 0 ? `+${n}` : `${n}`;
}

type Props = {
  value: number;
  /** compact: thin bar for tables; default: fuller desk visual */
  size?: 'sm' | 'md';
  showLabel?: boolean;
  /** Deep reports get stronger score ink; core stays quieter. */
  reportType?: ReportType | string | null;
};

export function ScoreMeter({
  value,
  size = 'sm',
  showLabel = true,
  reportType,
}: Props) {
  const score = clampScore(value);
  // Map −100…+100 → 0…100% for marker position
  const pct = ((score + 100) / 200) * 100;
  const tall = size === 'md';
  const deep = isDeepReport(reportType);

  return (
    <div className={`flex min-w-0 items-center ${tall ? 'gap-3' : 'gap-2'}`}>
      <div
        className={`relative min-w-0 flex-1 overflow-visible ${tall ? 'h-2.5 w-40' : 'h-1.5 w-20'}`}
        role="meter"
        aria-valuemin={-100}
        aria-valuemax={100}
        aria-valuenow={score}
        aria-label={deep ? 'AI score (deep report)' : 'AI score'}
      >
        <div
          className="absolute inset-0 rounded-full"
          style={{
            background:
              'linear-gradient(90deg, var(--color-sell) 0%, color-mix(in oklch, var(--color-hold) 80%, var(--color-surface-3)) 50%, var(--color-buy) 100%)',
            opacity: 0.9,
          }}
        />
        {/* Neutral tick */}
        <div
          className="absolute top-0 bottom-0 w-px bg-[var(--color-text-primary)]/35"
          style={{ left: '50%', transform: 'translateX(-50%)' }}
        />
        {/* Score marker */}
        <div
          className={`absolute top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full border border-[var(--color-surface-0)] bg-[var(--color-text-primary)] shadow-sm transition-[left] duration-500 ${
            tall ? 'h-3.5 w-3.5' : 'h-2.5 w-2.5'
          }`}
          style={{ left: `${pct}%` }}
        />
      </div>
      {showLabel && (
        <span
          className={`shrink-0 font-mono tabular-nums ${
            tall ? 'text-sm' : 'text-xs'
          } ${deep ? 'font-semibold text-[var(--color-text-primary)]' : 'font-medium'}`}
          style={
            deep
              ? undefined
              : {
                  color:
                    score > 15
                      ? 'var(--color-buy)'
                      : score < -15
                        ? 'var(--color-sell)'
                        : 'var(--color-hold)',
                }
          }
          title={deep ? 'Deep report' : undefined}
        >
          {formatScore(score)}
        </span>
      )}
    </div>
  );
}
