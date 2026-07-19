/** Kronos forecast chart — actual price history + 20-day forecast with confidence band. */
import { LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, ReferenceLine } from 'recharts';
import type { ForecastPoint } from '../api/types';

interface Props {
  forecast: ForecastPoint[];
  lastActual: number;
  lastDate: string;
  priceHistory?: { date: string; close: number }[];
}

export function ForecastChart({ forecast, lastActual, lastDate }: Props) {
  if (!forecast || forecast.length === 0) return null;

  // Build chart data: last actual point + forecast points
  const data = [
    { date: lastDate, close: lastActual, type: 'actual', label: 'Last actual' },
    ...forecast.map((f) => ({
      date: f.date,
      close: f.close,
      high: f.high,
      low: f.low,
      type: 'forecast',
      label: f.date,
    })),
  ];

  return (
    <div style={{ marginTop: 12 }}>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data} margin={{ top: 10, right: 30, left: 10, bottom: 10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-surface-3)" />
          <XAxis
            dataKey="date"
            tick={{ fill: 'var(--color-text-muted)', fontSize: 10 }}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fill: 'var(--color-text-muted)', fontSize: 10 }}
            domain={['auto', 'auto']}
          />
          <Tooltip
            contentStyle={{
              background: 'var(--color-surface-1)',
              border: '1px solid var(--color-surface-3)',
              borderRadius: 8,
              color: 'var(--color-text-primary)',
              fontSize: 12,
            }}
            labelStyle={{ color: 'var(--color-text-muted)', fontWeight: 600 }}
          />
          <ReferenceLine
            x={lastDate}
            stroke="var(--color-text-muted)"
            strokeDasharray="6 3"
            label={{ value: 'Now', fill: 'var(--color-text-muted)', fontSize: 10 }}
          />
          {/* Confidence band */}
          <Line
            type="monotone"
            dataKey="high"
            stroke="var(--color-accent)"
            strokeOpacity={0.15}
            dot={false}
            strokeWidth={0}
            legendType="none"
          />
          <Line
            type="monotone"
            dataKey="low"
            stroke="var(--color-accent)"
            strokeOpacity={0.15}
            dot={false}
            strokeWidth={0}
            fillOpacity={0.08}
            fill="var(--color-accent)"
          />
          {/* Main forecast line */}
          <Line
            type="monotone"
            dataKey="close"
            stroke="var(--color-accent)"
            strokeWidth={2}
            dot={false}
            strokeDasharray="4 2"
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}