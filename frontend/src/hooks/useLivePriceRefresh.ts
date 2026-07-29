import { useEffect, useId, useMemo } from 'react';
import { useLivePrice } from '../context/LivePriceContext';

/**
 * Register on-screen tickers for the shared 5-minute live price refresh loop.
 * During US RTH with the tab visible, the provider backfills 1m bars from Yahoo
 * and invalidates quotes/chart queries.
 */
export function useLivePriceRefresh(
  tickers: string[],
  opts?: { enabled?: boolean; deferMs?: number },
) {
  const id = useId();
  const { register, unregister, lastLiveAt, nextRefreshAt } = useLivePrice();
  const enabled = opts?.enabled !== false;
  const deferMs = opts?.deferMs ?? 0;

  const listKey = useMemo(() => {
    const uniq: string[] = [];
    const seen = new Set<string>();
    for (const raw of tickers) {
      const t = (raw || '').trim().toUpperCase();
      if (!t || seen.has(t)) continue;
      seen.add(t);
      uniq.push(t);
    }
    return uniq.join(',');
  }, [tickers]);

  useEffect(() => {
    const symbols = listKey ? listKey.split(',') : [];
    register(id, { tickers: symbols, enabled: enabled && symbols.length > 0, deferMs });
    return () => unregister(id);
  }, [id, listKey, enabled, deferMs, register, unregister]);

  return { lastLiveAt, nextRefreshAt };
}
