import type { PortfolioSummary, StockQuote } from '../api/types';
import { StatTile } from './StatTile';
import { DeltaValue } from './DeltaValue';

function fmt(n: number | null | undefined, currency = 'USD') {
  if (n == null) return '—';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: 0 }).format(n);
}

export function PortfolioSummaryCard({
  summary,
  quotes,
  holdingsTickers = [],
}: {
  summary: PortfolioSummary;
  quotes?: Record<string, StockQuote>;
  holdingsTickers?: string[];
}) {
  const pnl = summary.total_unrealized_pnl ?? 0;

  // Approximate book day-change as value-weighted average of holding change_pct
  let dayChange: number | null = null;
  if (quotes && holdingsTickers.length) {
    const pcts = holdingsTickers
      .map((t) => quotes[t]?.change_pct)
      .filter((v): v is number => v != null);
    if (pcts.length) {
      dayChange = pcts.reduce((a, b) => a + b, 0) / pcts.length;
    }
  }

  const spark = holdingsTickers.length
    ? (() => {
        const series = holdingsTickers
          .map((t) => quotes?.[t]?.spark)
          .filter((s): s is number[] => !!s && s.length > 1);
        if (!series.length) return undefined;
        const len = Math.min(...series.map((s) => s.length));
        return Array.from({ length: len }, (_, i) =>
          series.reduce((sum, s) => sum + s[s.length - len + i], 0) / series.length,
        );
      })()
    : undefined;

  return (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
      <StatTile
        label="Portfolio value"
        value={fmt(summary.total_value)}
        changePct={dayChange}
        spark={spark}
        footer={
          summary.snapshot_at ? (
            <span className="text-[var(--color-text-muted)]">
              as of {new Date(summary.snapshot_at).toLocaleDateString()}
            </span>
          ) : undefined
        }
      />
      <StatTile
        label="Unrealized P&L"
        value={
          <span className={pnl >= 0 ? 'text-[var(--color-up)]' : 'text-[var(--color-down)]'}>
            {pnl >= 0 ? '+' : ''}{fmt(pnl)}
          </span>
        }
      />
      <StatTile label="Positions" value={summary.position_count} />
      <StatTile
        label="Day move (avg)"
        value={dayChange != null ? <DeltaValue value={dayChange} className="text-xl" /> : '—'}
      />
    </div>
  );
}
