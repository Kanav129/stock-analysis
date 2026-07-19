import type { Rating } from '../api/types';

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

export function RatingBadge({ rating }: { rating: Rating | string }) {
  const key = (rating?.toUpperCase().replace(/[\s-]+/g, '_') as Rating) || 'HOLD';
  const label = labels[key] || key.replace(/_/g, ' ');
  const tone = classByRating[key] || classByRating.HOLD;

  return (
    <span className={`rating-badge ${tone}`}>
      {label}
    </span>
  );
}
