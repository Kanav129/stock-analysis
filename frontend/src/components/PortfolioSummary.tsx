import type { PortfolioSummary } from '../api/types';
import { DeltaValue } from './DeltaValue';
import { SensitiveValue } from './SensitiveValue';

function fmt(n: number | null | undefined, currency = 'USD') {
  if (n == null) return '—';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: 0 }).format(n);
}

/** Unrealized return vs cost basis; falls back when API/cache omit the field. */
function overallChangePct(summary: PortfolioSummary): number | null {
  const fromApi = summary.overall_change_pct;
  if (fromApi != null && !Number.isNaN(fromApi)) return fromApi;
  const value = summary.total_value ?? 0;
  const pnl = summary.total_unrealized_pnl ?? 0;
  const cost = value - pnl;
  if (!cost) return null;
  return Math.round((pnl / cost) * 10000) / 100;
}

export function PortfolioSummaryCard({ summary }: { summary: PortfolioSummary }) {
  const pnl = summary.total_unrealized_pnl ?? 0;
  const pnlUp = pnl >= 0;
  const overallPct = overallChangePct(summary);

  return (
    <div
      className="flex flex-wrap items-baseline gap-x-3 gap-y-1.5 border-b border-[var(--gridline)] pb-2"
      aria-label="Portfolio summary"
    >
      <div className="inline-flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="font-mono text-[length:var(--text-label)] text-[var(--color-text-muted)]">
          Value
        </span>
        <span className="font-mono text-[length:var(--text-data)] font-semibold tabular-nums text-[var(--color-text-primary)]">
          <SensitiveValue>{fmt(summary.total_value)}</SensitiveValue>
        </span>
        <span className="inline-flex items-baseline gap-x-1.5 font-mono text-[length:var(--text-label)] tabular-nums">
          <span className="text-[var(--color-text-muted)]">Day</span>
          <SensitiveValue>
            <DeltaValue value={summary.day_change_pct} className="text-[length:var(--text-label)] font-semibold" />
          </SensitiveValue>
        </span>
      </div>
      <span className="hidden h-3 w-px self-center bg-[var(--gridline)] sm:inline-block" aria-hidden="true" />
      <div className="inline-flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="font-mono text-[length:var(--text-label)] text-[var(--color-text-muted)]">
          Unrealized P&L
        </span>
        <span
          className={`font-mono text-[length:var(--text-data)] font-semibold tabular-nums ${
            pnlUp ? 'text-[var(--color-up)]' : 'text-[var(--color-down)]'
          }`}
        >
          <SensitiveValue>
            {pnlUp ? '+' : ''}
            {fmt(pnl)}
          </SensitiveValue>
        </span>
        <span className="inline-flex items-baseline gap-x-1.5 font-mono text-[length:var(--text-label)] tabular-nums">
          <span className="text-[var(--color-text-muted)]">Overall</span>
          <SensitiveValue>
            <DeltaValue value={overallPct} className="text-[length:var(--text-label)] font-semibold" />
          </SensitiveValue>
        </span>
      </div>
      {(summary.snapshot_at || summary.position_count != null) && (
        <>
          <span className="hidden h-3 w-px self-center bg-[var(--gridline)] sm:inline-block" aria-hidden="true" />
          <span className="text-[length:var(--text-label)] tabular-nums text-[var(--color-text-muted)]">
            {summary.snapshot_at
              ? `as of ${new Date(summary.snapshot_at).toLocaleDateString()}`
              : null}
            {summary.snapshot_at && summary.position_count != null ? ' · ' : null}
            {summary.position_count != null ? `${summary.position_count} positions` : null}
          </span>
        </>
      )}
    </div>
  );
}
