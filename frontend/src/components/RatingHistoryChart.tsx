import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { StockRating } from '../api/types';
import { AnalysisErrorIcon } from './AnalysisErrorIcon';

function isFailed(h: StockRating) {
  return h.analysis_failed ?? h.decision_ok === false;
}

function dayKey(iso: string) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

function formatTick(iso: string, showTime: boolean) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  if (showTime) {
    return d.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  }
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function formatTooltipDate(iso: string) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

export function RatingHistoryChart({ history }: { history: StockRating[] }) {
  if (!history.length) {
    return (
      <p className="text-sm text-[var(--color-text-muted)]">
        No rating history yet. Run analysis to generate ratings.
      </p>
    );
  }

  const chronological = [...history].reverse();
  const failedAttempts = chronological
    .filter(isFailed)
    .map((h) => ({
      createdAt: h.created_at,
      analysisError: h.error_message ?? h.analysis_error,
      dateLabel: formatTick(h.created_at, true),
    }));

  // Successful scores only — skip failures so the line flows without gaps.
  const successes = chronological.filter((h) => !isFailed(h) && h.score != null);
  const dayCounts = successes.reduce<Record<string, number>>((acc, h) => {
    const k = dayKey(h.created_at);
    acc[k] = (acc[k] ?? 0) + 1;
    return acc;
  }, {});
  const showTime = Object.values(dayCounts).some((n) => n > 1);

  const chartData = successes.map((h, i) => ({
    i,
    score: h.score as number,
    rating: h.rating,
    createdAt: h.created_at,
    tick: formatTick(h.created_at, showTime),
  }));

  if (!chartData.length) {
    return (
      <div className="w-full">
        <p className="text-sm text-[var(--color-text-muted)]">
          No successful ratings yet — only failed analysis attempts so far.
        </p>
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
                {point.dateLabel}: analysis failed
              </span>
            ))}
          </div>
        ) : null}
      </div>
    );
  }

  const xMax = Math.max(chartData.length - 1, 0);
  const tickIndexes =
    chartData.length <= 6
      ? chartData.map((p) => p.i)
      : [
          0,
          ...Array.from({ length: 3 }, (_, k) =>
            Math.round(((k + 1) * xMax) / 4),
          ),
          xMax,
        ].filter((v, idx, arr) => arr.indexOf(v) === idx);

  return (
    <div className="w-full">
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
            <CartesianGrid
              stroke="var(--gridline)"
              strokeDasharray="3 3"
              vertical={false}
            />
            <XAxis
              dataKey="i"
              type="number"
              domain={[0, xMax]}
              ticks={tickIndexes}
              tickFormatter={(v) => {
                const pt = chartData[Number(v)];
                return pt?.tick ?? '';
              }}
              tick={{
                fill: 'var(--color-text-muted)',
                fontSize: 11,
                fontFamily: 'var(--font-mono)',
              }}
              axisLine={{ stroke: 'var(--gridline)' }}
              tickLine={false}
              minTickGap={28}
              height={28}
              allowDecimals={false}
            />
            <YAxis
              yAxisId="score"
              tick={{
                fill: 'var(--color-text-muted)',
                fontSize: 11,
                fontFamily: 'var(--font-mono)',
              }}
              axisLine={{ stroke: 'var(--gridline)' }}
              tickLine={false}
              domain={[-100, 100]}
              width={36}
            />
            <ReferenceLine
              yAxisId="score"
              y={0}
              stroke="var(--color-text-muted)"
              strokeDasharray="4 4"
              strokeOpacity={0.55}
            />
            <Tooltip
              contentStyle={{
                background: 'var(--color-surface-1)',
                border: '1px solid var(--color-surface-3)',
                borderRadius: 12,
                boxShadow: 'var(--surface-ring)',
              }}
              labelFormatter={(_label, payload) => {
                const iso = (payload?.[0]?.payload as { createdAt?: string } | undefined)
                  ?.createdAt;
                return iso ? formatTooltipDate(iso) : '';
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
              stroke="var(--color-accent)"
              strokeWidth={2}
              dot={{
                r: 3.5,
                fill: 'var(--color-accent)',
                stroke: 'var(--color-surface-1)',
                strokeWidth: 2,
              }}
              activeDot={{
                r: 5,
                fill: 'var(--color-accent)',
                stroke: 'var(--color-text-primary)',
                strokeWidth: 1.5,
              }}
              connectNulls
              isAnimationActive
              animationDuration={420}
              animationEasing="ease-out"
            />
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
              {point.dateLabel}: analysis failed
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}
