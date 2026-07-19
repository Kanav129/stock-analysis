import { Link } from 'react-router-dom';
import type { Rating } from '../api/types';
import { DeltaValue } from './DeltaValue';
import { RatingBadge } from './RatingBadge';

export function HeatTile({
  ticker,
  price,
  changePct,
  rating,
}: {
  ticker: string;
  price?: number | null;
  changePct?: number | null;
  rating?: Rating | null;
}) {
  const pct = changePct ?? 0;
  const intensity = Math.min(Math.abs(pct) / 4, 1);
  const bg =
    changePct == null
      ? 'transparent'
      : pct >= 0
        ? `color-mix(in oklch, var(--color-up) ${12 + intensity * 28}%, var(--color-surface-1))`
        : `color-mix(in oklch, var(--color-down) ${12 + intensity * 28}%, var(--color-surface-1))`;

  return (
    <Link
      to={`/stock/${ticker}`}
      className="heat-tile"
      style={{ background: bg }}
    >
      <div className="flex items-center justify-between gap-1">
        <span className="font-mono text-sm font-semibold text-[var(--color-text-primary)]">{ticker}</span>
        {rating && <RatingBadge rating={rating} />}
      </div>
      <div className="mt-1 flex items-baseline justify-between gap-2">
        <span className="font-mono text-xs text-[var(--color-text-secondary)]">
          {price != null ? `$${price.toFixed(2)}` : '—'}
        </span>
        <DeltaValue value={changePct} className="text-xs" />
      </div>
    </Link>
  );
}
