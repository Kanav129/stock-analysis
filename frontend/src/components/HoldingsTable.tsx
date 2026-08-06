import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import type { Holding, Rating, StockQuote, StockRating } from '../api/types';
import { patchDeskCache, readDeskCache } from '../lib/deskCache';
import { AnalysisErrorIcon } from './AnalysisErrorIcon';
import { RatingBadge } from './RatingBadge';
import { ScoreMeter } from './ScoreMeter';
import { Sparkline } from './Sparkline';
import { DeltaValue } from './DeltaValue';
import { CompactTable } from './CompactTable';
import { SensitiveValue } from './SensitiveValue';

function fmt(n: number | null | undefined) {
  if (n == null) return '—';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(n);
}

const RATING_RANK: Record<Rating, number> = {
  STRONG_SELL: 0,
  SELL: 1,
  REDUCE: 2,
  HOLD: 3,
  ACCUMULATE: 4,
  BUY: 5,
  STRONG_BUY: 6,
};

type SortKey = 'ticker' | 'qty' | 'price' | 'chg' | 'spark' | 'value' | 'pnl' | 'rating' | 'score';
type SortDir = 'asc' | 'desc';

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: 'ticker', label: 'Ticker' },
  { key: 'qty', label: 'Qty' },
  { key: 'price', label: 'Price' },
  { key: 'chg', label: 'Chg' },
  { key: 'spark', label: '30d' },
  { key: 'value', label: 'Value' },
  { key: 'pnl', label: 'P&L' },
  { key: 'rating', label: 'Rating' },
  { key: 'score', label: 'Score' },
];

/** Numeric / money columns default to desc on first click; ticker to asc. */
const DEFAULT_DIR: Record<SortKey, SortDir> = {
  ticker: 'asc',
  qty: 'desc',
  price: 'desc',
  chg: 'desc',
  spark: 'desc',
  value: 'desc',
  pnl: 'desc',
  rating: 'desc',
  score: 'desc',
};

const SORT_KEYS = new Set<string>(COLUMNS.map((c) => c.key));

function readHoldingsSort(): { sortKey: SortKey; sortDir: SortDir } {
  const cached = readDeskCache();
  const key = cached?.holdingsSortKey;
  const dir = cached?.holdingsSortDir;
  if (key && SORT_KEYS.has(key) && (dir === 'asc' || dir === 'desc')) {
    return { sortKey: key as SortKey, sortDir: dir };
  }
  return { sortKey: 'value', sortDir: 'desc' };
}

function sparkReturn(spark: number[] | undefined): number | null {
  if (!spark || spark.length < 2) return null;
  const first = spark[0];
  const last = spark[spark.length - 1];
  if (first === 0) return null;
  return ((last - first) / first) * 100;
}

function cmpNullable(a: number | null, b: number | null, dir: SortDir): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  const d = a - b;
  return dir === 'asc' ? d : -d;
}

function SortHeader({
  label,
  active,
  dir,
  onClick,
}: {
  label: string;
  active: boolean;
  dir: SortDir;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={`inline-flex cursor-pointer items-center gap-1 border-0 bg-transparent p-0 font-[inherit] tracking-[inherit] uppercase ${
        active ? 'text-[var(--color-text-primary)]' : 'text-inherit hover:text-[var(--color-text-primary)]'
      }`}
      onClick={onClick}
      aria-label={`Sort by ${label}${active ? `, ${dir === 'asc' ? 'ascending' : 'descending'}` : ''}`}
    >
      <span>{label}</span>
      <span
        className={`text-[length:var(--text-label)] leading-none ${
          active ? 'text-[var(--color-accent)] opacity-90' : 'opacity-45'
        }`}
        aria-hidden="true"
      >
        {active ? (dir === 'asc' ? '▲' : '▼') : '↕'}
      </span>
    </button>
  );
}

export function HoldingsTable({
  holdings,
  ratings,
  quotes,
}: {
  holdings: Holding[];
  ratings: StockRating[];
  quotes?: Record<string, StockQuote>;
}) {
  const ratingMap = useMemo(
    () => Object.fromEntries(ratings.map((r) => [r.ticker, r])),
    [ratings],
  );
  const [sortKey, setSortKey] = useState<SortKey>(() => readHoldingsSort().sortKey);
  const [sortDir, setSortDir] = useState<SortDir>(() => readHoldingsSort().sortDir);

  useEffect(() => {
    patchDeskCache({ holdingsSortKey: sortKey, holdingsSortDir: sortDir });
  }, [sortKey, sortDir]);

  const sorted = useMemo(() => {
    const rows = [...holdings];
    rows.sort((a, b) => {
      const ra = ratingMap[a.ticker];
      const rb = ratingMap[b.ticker];
      const qa = quotes?.[a.ticker];
      const qb = quotes?.[b.ticker];

      let result = 0;
      switch (sortKey) {
        case 'ticker':
          result =
            sortDir === 'asc'
              ? a.ticker.localeCompare(b.ticker)
              : b.ticker.localeCompare(a.ticker);
          break;
        case 'qty':
          result = cmpNullable(a.quantity, b.quantity, sortDir);
          break;
        case 'price':
          result = cmpNullable(
            a.market_price ?? qa?.latest_close ?? null,
            b.market_price ?? qb?.latest_close ?? null,
            sortDir,
          );
          break;
        case 'chg':
          result = cmpNullable(qa?.change_pct ?? null, qb?.change_pct ?? null, sortDir);
          break;
        case 'spark':
          result = cmpNullable(sparkReturn(qa?.spark), sparkReturn(qb?.spark), sortDir);
          break;
        case 'value':
          result = cmpNullable(a.market_value, b.market_value, sortDir);
          break;
        case 'pnl':
          result = cmpNullable(a.unrealized_pnl, b.unrealized_pnl, sortDir);
          break;
        case 'rating':
          result = cmpNullable(
            ra?.rating ? RATING_RANK[ra.rating] : null,
            rb?.rating ? RATING_RANK[rb.rating] : null,
            sortDir,
          );
          break;
        case 'score':
          result = cmpNullable(ra?.score ?? null, rb?.score ?? null, sortDir);
          break;
      }
      if (result !== 0) return result;
      return a.ticker.localeCompare(b.ticker);
    });
    return rows;
  }, [holdings, quotes, ratingMap, sortDir, sortKey]);

  if (!holdings.length) {
    return (
      <p className="text-sm text-[var(--color-text-secondary)]">
        No holdings yet. Use <span className="font-medium">Sync holdings</span> to
        import IBKR stock/ETF positions, then run Analysis for ratings.
      </p>
    );
  }

  const headers = COLUMNS.map((col) => (
    <SortHeader
      key={col.key}
      label={col.label}
      active={sortKey === col.key}
      dir={sortDir}
      onClick={() => {
        if (sortKey === col.key) {
          setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
        } else {
          setSortKey(col.key);
          setSortDir(DEFAULT_DIR[col.key]);
        }
      }}
    />
  ));

  return (
    <CompactTable headers={headers} centerCols={[7]} caption="Holdings with ratings and scores">
      {sorted.map((h) => {
        const r = ratingMap[h.ticker];
        const q = quotes?.[h.ticker];
        const pnl = h.unrealized_pnl ?? 0;
        const up = pnl >= 0;
        return (
          <tr key={h.ticker}>
            <td>
              <Link to={`/stock/${h.ticker}`} className="font-mono font-semibold text-[var(--color-accent)] hover:underline">
                {h.ticker}
              </Link>
            </td>
            <td className="font-mono">
              <SensitiveValue>{h.quantity.toFixed(2)}</SensitiveValue>
            </td>
            <td className="font-mono">{fmt(h.market_price ?? q?.latest_close)}</td>
            <td><DeltaValue value={q?.change_pct} /></td>
            <td><Sparkline data={q?.spark ?? []} /></td>
            <td className="font-mono">
              <SensitiveValue>{fmt(h.market_value)}</SensitiveValue>
            </td>
            <td className="font-mono">
              <SensitiveValue>
                <span className={up ? 'text-[var(--color-up)]' : 'text-[var(--color-down)]'}>
                  {fmt(h.unrealized_pnl)}
                </span>
              </SensitiveValue>
            </td>
            <td className="is-center">
              <span className="inline-flex items-center justify-center gap-1">
                {r?.rating ? (
                  <RatingBadge rating={r.rating} reportType={r.report_type} />
                ) : !r?.analysis_failed ? (
                  <span className="text-[var(--color-text-muted)]">—</span>
                ) : null}
                <AnalysisErrorIcon
                  analysisFailed={r?.analysis_failed}
                  analysisError={r?.analysis_error}
                  failedAt={r?.failed_at}
                />
              </span>
            </td>
            <td>
              {r?.score != null ? (
                <ScoreMeter value={r.score} reportType={r.report_type} />
              ) : (
                '—'
              )}
            </td>
          </tr>
        );
      })}
    </CompactTable>
  );
}
