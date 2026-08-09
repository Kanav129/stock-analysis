import type { Rating, ReportType } from '../api/types';
import { isDeepReport, normalizeReportDepth } from '../lib/reportDepth';

const labels: Record<string, string> = {
  STRONG_BUY: 'Strong Buy',
  BUY: 'Buy',
  ACCUMULATE: 'Accumulate',
  HOLD: 'Hold',
  REDUCE: 'Reduce',
  SELL: 'Sell',
  STRONG_SELL: 'Strong Sell',
};

const classByRating: Record<string, string> = {
  STRONG_BUY: 'rating-badge--strong-buy',
  BUY: 'rating-badge--buy',
  ACCUMULATE: 'rating-badge--accumulate',
  HOLD: 'rating-badge--hold',
  REDUCE: 'rating-badge--reduce',
  SELL: 'rating-badge--sell',
  STRONG_SELL: 'rating-badge--strong-sell',
};

export function RatingBadge({
  rating,
  reportType,
}: {
  rating: Rating | string;
  /** Soft azure pip + luminous wash when `deep`; core / unknown stay plain. */
  reportType?: ReportType | string | null;
}) {
  const key = (rating?.toUpperCase().replace(/[\s-]+/g, '_') as Rating) || 'HOLD';
  const label = labels[key] || key.replace(/_/g, ' ');
  const tone = classByRating[key] || classByRating.HOLD;
  const depth = normalizeReportDepth(reportType);
  const deep = isDeepReport(depth);

  return (
    <span
      className={`rating-badge ${tone}${deep ? ' rating-badge--deep' : ''}`}
      title={deep ? 'Deep report' : depth === 'core' ? 'Core report' : undefined}
    >
      {deep ? <span className="rating-badge__pip" aria-hidden /> : null}
      {deep ? <span className="sr-only">Deep report. </span> : null}
      {label}
    </span>
  );
}
