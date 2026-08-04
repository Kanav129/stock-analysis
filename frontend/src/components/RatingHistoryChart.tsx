import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { StockRating } from '../api/types';
import { AnalysisErrorIcon } from './AnalysisErrorIcon';

export function RatingHistoryChart({ history }: { history: StockRating[] }) {
  if (!history.length) {
    return <p className="text-sm text-[var(--color-text-muted)]">No rating history yet. Run analysis to generate ratings.</p>;
  }

  const chartData = [...history]
    .reverse()
    .map((h) => ({
      date: new Date(h.created_at).toLocaleDateString(),
      score: h.score,
      rating: h.rating,
      analysisFailed: h.analysis_failed ?? h.decision_ok === false,
      analysisError: h.error_message ?? h.analysis_error,
      createdAt: h.created_at,
    }));
  const failedAttempts = chartData.filter((point) => point.analysisFailed);

  return (
    <div className="w-full">
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData}>
          <CartesianGrid stroke="oklch(0.25 0.035 260)" strokeDasharray="3 3" />
          <XAxis dataKey="date" tick={{ fill: 'oklch(0.55 0.02 260)', fontSize: 11 }} />
          <YAxis
            yAxisId="score"
            tick={{ fill: 'oklch(0.55 0.02 260)', fontSize: 11 }}
            domain={[-100, 100]}
          />
          <ReferenceLine yAxisId="score" y={0} stroke="oklch(0.45 0.02 260)" strokeDasharray="4 4" />
          <Tooltip
            contentStyle={{
              background: 'oklch(0.17 0.025 260)',
              border: '1px solid oklch(0.25 0.035 260)',
              borderRadius: 8,
            }}
            formatter={(value, _name, item) => {
              const rating = (item?.payload as { rating?: string } | undefined)?.rating;
              return [`${value}${rating ? ` (${rating})` : ''}`, 'AI score'];
            }}
          />
          <Line
            yAxisId="score"
            type="monotone"
            dataKey="score"
            stroke="oklch(0.72 0.14 250)"
            strokeWidth={2}
            dot
          />
          {failedAttempts.map((point, index) => (
            <ReferenceDot
              key={`${point.createdAt}-${index}`}
              yAxisId="score"
              x={point.date}
              y={0}
              r={5}
              fill="var(--color-down)"
              stroke="var(--color-surface)"
              strokeWidth={2}
              label={{
                value: '!',
                position: 'top',
                fill: 'var(--color-down)',
                fontSize: 11,
                fontWeight: 700,
              }}
            />
          ))}
        </LineChart>
        </ResponsiveContainer>
      </div>
      {failedAttempts.length ? (
        <div
          className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-[var(--color-down)]"
          aria-label="Failed analysis attempts"
        >
          {failedAttempts.map((point, index) => (
            <span key={`${point.createdAt}-failure-${index}`} className="inline-flex items-center gap-1">
              <AnalysisErrorIcon
                analysisFailed
                analysisError={point.analysisError}
                failedAt={point.createdAt}
              />
              {point.date}: analysis failed
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}
