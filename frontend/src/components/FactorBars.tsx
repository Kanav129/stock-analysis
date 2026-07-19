const FACTOR_LABELS: Record<string, string> = {
  value: 'Value',
  growth: 'Growth',
  quality: 'Quality',
  momentum: 'Momentum',
  low_risk: 'Low Risk',
  sentiment: 'Sentiment',
  market: 'Market',
  fundamentals: 'Fundamentals',
  news: 'News',
};

function barColor(score: number): string {
  if (score >= 65) return 'var(--color-up)';
  if (score >= 40) return 'var(--color-hold)';
  return 'var(--color-down)';
}

export function FactorBars({
  scores,
  compact = false,
}: {
  scores: Record<string, number>;
  compact?: boolean;
}) {
  const entries = Object.entries(scores).filter(([k]) => typeof scores[k] === 'number');
  if (!entries.length) return null;

  return (
    <div className={`factor-bars ${compact ? 'factor-bars--compact' : ''}`}>
      {entries.map(([key, score]) => (
        <div key={key} className="factor-bars__row">
          <span className="factor-bars__label">{FACTOR_LABELS[key] || key}</span>
          <div className="factor-bars__track">
            <div
              className="factor-bars__fill"
              style={{ width: `${Math.max(0, Math.min(100, score))}%`, background: barColor(score) }}
            />
          </div>
          <span className="factor-bars__score font-mono">{Math.round(score)}</span>
        </div>
      ))}
    </div>
  );
}
