import { Link } from 'react-router-dom';
import type { Holding, StockQuote, StockRating } from '../api/types';
import { RatingBadge } from './RatingBadge';
import { ScoreMeter } from './ScoreMeter';
import { Sparkline } from './Sparkline';
import { DeltaValue } from './DeltaValue';
import { CompactTable } from './CompactTable';

function fmt(n: number | null | undefined) {
  if (n == null) return '—';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(n);
}

export function HoldingsTable({
  holdings,
  ratings,
  quotes,
}: {
  holdings: Holding[];
  ratings: StockRating[];
  quotes?: Record<string, StockQuote>;
}) {
  const ratingMap = Object.fromEntries(ratings.map((r) => [r.ticker, r]));

  if (!holdings.length) {
    return (
      <div className="rounded-[var(--panel-radius)] border border-[var(--color-surface-3)] bg-[var(--color-surface-1)] p-6 text-center">
        <p className="font-display text-sm text-[var(--color-text-primary)]">No holdings yet</p>
        <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
          Add tickers to your watchlist to start tracking and running analysis.
        </p>
      </div>
    );
  }

  return (
    <CompactTable
      headers={['Ticker', 'Qty', 'Price', 'Chg', '30d', 'Value', 'P&L', 'Rating', 'Score']}
      centerCols={[7]}
    >
      {holdings.map((h) => {
        const r = ratingMap[h.ticker];
        const q = quotes?.[h.ticker];
        const pnl = h.unrealized_pnl ?? 0;
        const up = pnl >= 0;
        return (
          <tr key={h.ticker}>
            <td>
              <Link to={`/stock/${h.ticker}`} className="font-mono font-semibold text-[var(--color-accent)] hover:underline">
                {h.ticker}
              </Link>
            </td>
            <td className="font-mono">{h.quantity.toFixed(2)}</td>
            <td className="font-mono">{fmt(h.market_price ?? q?.latest_close)}</td>
            <td><DeltaValue value={q?.change_pct} /></td>
            <td><Sparkline data={q?.spark ?? []} /></td>
            <td className="font-mono">{fmt(h.market_value)}</td>
            <td className={`font-mono ${up ? 'text-[var(--color-up)]' : 'text-[var(--color-down)]'}`}>
              {fmt(h.unrealized_pnl)}
            </td>
            <td className="is-center">
              {r ? <RatingBadge rating={r.rating} /> : <span className="text-[var(--color-text-muted)]">—</span>}
            </td>
            <td>{r ? <ScoreMeter value={r.score} /> : '—'}</td>
          </tr>
        );
      })}
    </CompactTable>
  );
}
