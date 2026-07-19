import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import type { ChartPoint } from '../api/types';

export function PriceChart({ data, priceKey = 'close' }: { data: ChartPoint[]; priceKey?: string }) {
  if (!data.length) {
    return <p className="text-sm text-[var(--color-text-muted)]">No price data available.</p>;
  }

  const chartData = data
    .map((d) => ({
      date: String(d.date ?? d.Date ?? '').slice(0, 10),
      price: Number(d[priceKey] ?? d.close ?? 0),
    }))
    .filter((d) => d.date)
    .sort((a, b) => a.date.localeCompare(b.date));

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData}>
          <XAxis dataKey="date" tick={{ fill: 'oklch(0.55 0.02 260)', fontSize: 11 }} />
          <YAxis tick={{ fill: 'oklch(0.55 0.02 260)', fontSize: 11 }} domain={['auto', 'auto']} />
          <Tooltip
            contentStyle={{
              background: 'oklch(0.17 0.025 260)',
              border: '1px solid oklch(0.25 0.035 260)',
              borderRadius: 8,
            }}
          />
          <Line type="monotone" dataKey="price" stroke="oklch(0.72 0.14 250)" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
