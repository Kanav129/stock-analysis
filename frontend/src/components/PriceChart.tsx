import { useMemo } from 'react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { ChartPoint } from '../api/types';
import type { ChartRangeId } from './ChartRangeToggle';

export type { ChartRangeId };

/** US equity session timezone for intraday axis labels. */
const US_TZ = 'America/New_York';

type PlotPoint = {
  /** Ordinal index — equal spacing removes closed-market gaps on the x-axis. */
  i: number;
  ts: number;
  label: string;
  price: number;
  raw: string;
};

function parseTs(value: string): number {
  const t = Date.parse(value);
  return Number.isNaN(t) ? 0 : t;
}

function formatPrice(n: number): string {
  if (!Number.isFinite(n)) return '—';
  if (Math.abs(n) >= 1000) return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (Math.abs(n) >= 1) return n.toFixed(2);
  return n.toFixed(4);
}

function isIntradayRange(range: ChartRangeId): boolean {
  return range === '1' || range === '7' || range === '14' || range === '30';
}

function formatTick(ts: number, range: ChartRangeId): string {
  const d = new Date(ts);
  if (range === '1') {
    return d.toLocaleTimeString('en-US', {
      timeZone: US_TZ,
      hour: 'numeric',
      minute: '2-digit',
    });
  }
  if (range === '7' || range === '14') {
    return d.toLocaleString('en-US', {
      timeZone: US_TZ,
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
    });
  }
  if (range === '30') {
    return d.toLocaleString('en-US', {
      timeZone: US_TZ,
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
    });
  }
  if (range === 'all' || range === '365' || range === '180') {
    return d.toLocaleDateString(undefined, { month: 'short', year: '2-digit' });
  }
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function formatTooltipDate(ts: number, range: ChartRangeId): string {
  const d = new Date(ts);
  if (range === '1') {
    return d.toLocaleString('en-US', {
      timeZone: US_TZ,
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      timeZoneName: 'short',
    });
  }
  if (isIntradayRange(range)) {
    return d.toLocaleString('en-US', {
      timeZone: US_TZ,
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      timeZoneName: 'short',
    });
  }
  return d.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

/** Evenly spaced ordinal tick indices (not calendar-even). */
function buildOrdinalTicks(length: number, range: ChartRangeId): number[] {
  if (length <= 0) return [];
  const maxTicks =
    range === '1' ? 6 : range === '7' || range === '14' || range === '30' ? 7 : range === 'all' ? 6 : 8;
  if (length <= maxTicks) {
    return Array.from({ length }, (_, i) => i);
  }
  const ticks: number[] = [];
  const last = length - 1;
  for (let t = 0; t < maxTicks; t++) {
    const idx = Math.round((t * last) / (maxTicks - 1));
    if (!ticks.includes(idx)) ticks.push(idx);
  }
  return ticks;
}

export function PriceChart({
  data,
  priceKey = 'close',
  range = '90',
  interval,
  sessionDate,
}: {
  data: ChartPoint[];
  priceKey?: string;
  range?: ChartRangeId;
  /** Ladder interval from API (`1m`, `15m`, …). */
  interval?: string;
  /** US session calendar date for 1D charts (YYYY-MM-DD). */
  sessionDate?: string | null;
}) {
  const chartData = useMemo(() => {
    const mapped = data
      .map((d) => {
        const raw = String(d.date ?? d.Date ?? '');
        const ts = parseTs(raw);
        const price = Number(d[priceKey] ?? d.close ?? NaN);
        return { ts, raw, price };
      })
      .filter((d) => d.ts > 0 && Number.isFinite(d.price))
      .sort((a, b) => a.ts - b.ts);

    // Dedupe identical timestamps (keep last)
    const byTs = new Map<number, { ts: number; raw: string; price: number }>();
    for (const p of mapped) byTs.set(p.ts, p);

    return [...byTs.values()].map((p, i) => ({
      i,
      ts: p.ts,
      raw: p.raw,
      price: p.price,
      label: formatTick(p.ts, range),
    }));
  }, [data, priceKey, range]);

  const ticks = useMemo(() => buildOrdinalTicks(chartData.length, range), [chartData.length, range]);

  const delta = useMemo(() => {
    if (chartData.length < 2) return null;
    const first = chartData[0].price;
    const last = chartData[chartData.length - 1].price;
    if (!first) return null;
    const pct = ((last - first) / first) * 100;
    return { pct, up: pct >= 0 };
  }, [chartData]);

  if (!chartData.length) {
    return (
      <p className="text-sm text-[var(--color-text-muted)]">
        {range === '1'
          ? 'No session bars yet. Sync prices, or check after the next US trading day.'
          : 'No price data for this range. Sync prices or pick a wider window.'}
      </p>
    );
  }

  const stroke = 'var(--color-accent)';
  const fillId = `price-fill-${range}`;
  const deltaLabel =
    range === '1'
      ? sessionDate
        ? `session ${sessionDate}`
        : 'session'
      : 'range';
  const xMax = Math.max(0, chartData.length - 1);

  return (
    <div className="price-chart">
      {delta && (
        <p
          className={`price-chart__delta ${delta.up ? 'price-chart__delta--up' : 'price-chart__delta--down'}`}
        >
          {delta.up ? '+' : ''}
          {delta.pct.toFixed(2)}% over {deltaLabel}
          {interval ? (
            <span className="price-chart__interval"> · {interval} bars</span>
          ) : null}
        </p>
      )}
      <div className="price-chart__canvas">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
            <defs>
              <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={stroke} stopOpacity={0.22} />
                <stop offset="100%" stopColor={stroke} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid
              stroke="var(--gridline)"
              strokeDasharray="3 3"
              vertical={false}
            />
            <XAxis
              dataKey="i"
              type="number"
              domain={[0, xMax]}
              ticks={ticks}
              tickFormatter={(v) => {
                const idx = Number(v);
                const pt = chartData[idx];
                return pt ? formatTick(pt.ts, range) : '';
              }}
              tick={{ fill: 'var(--color-text-muted)', fontSize: 11, fontFamily: 'var(--font-mono)' }}
              axisLine={{ stroke: 'var(--gridline)' }}
              tickLine={false}
              minTickGap={36}
              height={28}
              allowDecimals={false}
            />
            <YAxis
              tick={{ fill: 'var(--color-text-muted)', fontSize: 11, fontFamily: 'var(--font-mono)' }}
              tickFormatter={(v) => formatPrice(Number(v))}
              domain={['auto', 'auto']}
              width={56}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip
              cursor={{ stroke: 'var(--color-text-muted)', strokeWidth: 1 }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const p = payload[0].payload as PlotPoint;
                return (
                  <div className="price-chart__tooltip">
                    <p className="price-chart__tooltip-date">{formatTooltipDate(p.ts, range)}</p>
                    <p className="price-chart__tooltip-price">{formatPrice(p.price)}</p>
                  </div>
                );
              }}
            />
            <Area
              type="monotone"
              dataKey="price"
              stroke={stroke}
              strokeWidth={2}
              fill={`url(#${fillId})`}
              dot={false}
              activeDot={{ r: 3, strokeWidth: 0, fill: stroke }}
              isAnimationActive
              animationDuration={280}
              animationEasing="ease-out"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
