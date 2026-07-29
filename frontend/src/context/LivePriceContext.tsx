import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { isUsRegularSession } from '../lib/usMarketHours';
import { LIVE_REFRESH_INTERVAL_MS } from '../lib/livePriceSchedule';

const GATE_CHECK_MS = 30_000;
const MAX_TICKERS = 40;
const MARKET_TICKERS = ['SPY', 'QQQ', 'IWM', 'DIA'];

type Registration = {
  tickers: string[];
  enabled: boolean;
  deferMs: number;
};

type LivePriceContextValue = {
  lastLiveAt: number | null;
  nextRefreshAt: number | null;
  isRefreshing: boolean;
  register: (id: string, reg: Registration) => void;
  unregister: (id: string) => void;
};

const LivePriceContext = createContext<LivePriceContextValue | null>(null);

function mergeTickers(regs: Map<string, Registration>): string[] {
  const seen = new Set<string>();
  const uniq: string[] = [];
  const add = (raw: string) => {
    const t = raw.trim().toUpperCase();
    if (!t || seen.has(t)) return;
    seen.add(t);
    uniq.push(t);
  };
  for (const t of MARKET_TICKERS) add(t);
  for (const reg of regs.values()) {
    if (!reg.enabled) continue;
    for (const t of reg.tickers) {
      add(t);
      if (uniq.length >= MAX_TICKERS) return uniq;
    }
  }
  return uniq;
}

function maxDefer(regs: Map<string, Registration>): number {
  let d = 0;
  for (const reg of regs.values()) {
    if (reg.enabled) d = Math.max(d, reg.deferMs);
  }
  return d;
}

export function LivePriceProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [regs, setRegs] = useState<Map<string, Registration>>(() => new Map());
  const [lastLiveAt, setLastLiveAt] = useState<number | null>(null);
  const [nextRefreshAt, setNextRefreshAt] = useState<number | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const register = useCallback((id: string, reg: Registration) => {
    setRegs((prev) => {
      const next = new Map(prev);
      next.set(id, reg);
      return next;
    });
  }, []);

  const unregister = useCallback((id: string) => {
    setRegs((prev) => {
      if (!prev.has(id)) return prev;
      const next = new Map(prev);
      next.delete(id);
      return next;
    });
  }, []);

  const tickers = useMemo(() => mergeTickers(regs), [regs]);
  const listKey = tickers.join(',');
  const deferMs = useMemo(() => maxDefer(regs), [regs]);

  const lastRunRef = useRef(0);
  const readyAtRef = useRef(0);

  useEffect(() => {
    if (!listKey) return;

    let cancelled = false;
    const symbols = listKey.split(',');
    readyAtRef.current = Date.now() + Math.max(0, deferMs);
    setNextRefreshAt(readyAtRef.current);

    const run = async (force: boolean) => {
      if (cancelled) return;
      if (Date.now() < readyAtRef.current) return;
      if (typeof document !== 'undefined' && document.visibilityState !== 'visible') {
        return;
      }
      if (!isUsRegularSession()) return;

      const now = Date.now();
      if (!force && now - lastRunRef.current < LIVE_REFRESH_INTERVAL_MS - 250) return;

      lastRunRef.current = now;
      setIsRefreshing(true);
      setNextRefreshAt(now + LIVE_REFRESH_INTERVAL_MS);

      try {
        const res = await api.livePriceRefresh(symbols);
        if (cancelled || res.skipped) return;
        await Promise.all([
          qc.invalidateQueries({ queryKey: ['quotes'] }),
          qc.invalidateQueries({ queryKey: ['chart'] }),
        ]);
        const at = Date.now();
        setLastLiveAt(at);
        setNextRefreshAt(at + LIVE_REFRESH_INTERVAL_MS);
      } catch {
        setNextRefreshAt(lastRunRef.current + LIVE_REFRESH_INTERVAL_MS);
      } finally {
        if (!cancelled) setIsRefreshing(false);
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
  }, [listKey, qc, deferMs]);

  const value = useMemo(
    () => ({ lastLiveAt, nextRefreshAt, isRefreshing, register, unregister }),
    [lastLiveAt, nextRefreshAt, isRefreshing, register, unregister],
  );

  return <LivePriceContext.Provider value={value}>{children}</LivePriceContext.Provider>;
}

export function useLivePrice() {
  const ctx = useContext(LivePriceContext);
  if (!ctx) throw new Error('useLivePrice must be used within LivePriceProvider');
  return ctx;
}
