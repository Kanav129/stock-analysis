import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine } from 'recharts';
import type { StockRating } from '../api/types';

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
    }));

  return (
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
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
