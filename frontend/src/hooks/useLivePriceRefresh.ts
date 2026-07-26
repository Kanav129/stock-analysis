import { useEffect, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { isUsRegularSession } from '../lib/usMarketHours';

const INTERVAL_MS = 5 * 60_000;
const GATE_CHECK_MS = 30_000;
const MAX_TICKERS = 40;

/**
 * During US RTH with the tab visible, every 5 minutes backfill on-screen
 * tickers' 1m bars from Yahoo, then invalidate quotes/chart queries.
 *
 * `deferMs` delays the first Yahoo call so Desk critical reads aren't starved
 * on cold start / reload.
 */
export function useLivePriceRefresh(
  tickers: string[],
  opts?: { enabled?: boolean; deferMs?: number },
): { lastLiveAt: number | null } {
  const qc = useQueryClient();
  const enabled = opts?.enabled !== false;
  const deferMs = opts?.deferMs ?? 0;
  const [lastLiveAt, setLastLiveAt] = useState<number | null>(null);
  const listKey = useMemo(() => {
    const uniq: string[] = [];
    const seen = new Set<string>();
    for (const raw of tickers) {
      const t = (raw || '').trim().toUpperCase();
      if (!t || seen.has(t)) continue;
      seen.add(t);
      uniq.push(t);
      if (uniq.length >= MAX_TICKERS) break;
    }
    return uniq.join(',');
  }, [tickers]);

  const lastRunRef = useRef(0);
  const readyAtRef = useRef(0);

  useEffect(() => {
    if (!enabled || !listKey) return;

    let cancelled = false;
    const symbols = listKey.split(',');
    readyAtRef.current = Date.now() + Math.max(0, deferMs);

    const run = async (force: boolean) => {
      if (cancelled) return;
      if (Date.now() < readyAtRef.current) return;
      if (typeof document !== 'undefined' && document.visibilityState !== 'visible') {
        return;
      }
      if (!isUsRegularSession()) return;

      const now = Date.now();
      if (!force && now - lastRunRef.current < INTERVAL_MS - 250) return;
      lastRunRef.current = now;

      try {
        const res = await api.livePriceRefresh(symbols);
        if (cancelled || res.skipped) return;
        await Promise.all([
          qc.invalidateQueries({ queryKey: ['quotes'] }),
          qc.invalidateQueries({ queryKey: ['chart'] }),
        ]);
        setLastLiveAt(Date.now());
      } catch {
        /* transient network / cold start — next tick retries */
      }
    };

    let bootTimer: number | undefined;
    if (deferMs > 0) {
      bootTimer = window.setTimeout(() => void run(true), deferMs);
    } else {
      void run(true);
    }
    const id = window.setInterval(() => void run(false), GATE_CHECK_MS);
    const onVis = () => {
      if (document.visibilityState === 'visible') void run(false);
    };
    document.addEventListener('visibilitychange', onVis);

    return () => {
      cancelled = true;
      if (bootTimer) window.clearTimeout(bootTimer);
      window.clearInterval(id);
      document.removeEventListener('visibilitychange', onVis);
    };
  }, [enabled, listKey, qc, deferMs]);

  return { lastLiveAt };
}
