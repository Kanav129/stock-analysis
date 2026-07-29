import { useEffect, useState } from 'react';
import { useLivePrice } from '../context/LivePriceContext';
import { formatCountdown, msUntil } from '../lib/livePriceSchedule';
import { isUsRegularSession } from '../lib/usMarketHours';

/**
 * Center-header badge during US RTH: live pulse + countdown to the next price refresh.
 */
export function LiveSessionIndicator() {
  const { nextRefreshAt, isRefreshing } = useLivePrice();
  const [sessionOpen, setSessionOpen] = useState(() => isUsRegularSession());
  const [visible, setVisible] = useState(
    () => typeof document === 'undefined' || document.visibilityState === 'visible',
  );
  const [countdown, setCountdown] = useState(() => formatCountdown(msUntil(nextRefreshAt)));

  useEffect(() => {
    const syncSession = () => setSessionOpen(isUsRegularSession());
    syncSession();
    const id = window.setInterval(syncSession, 30_000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    const onVis = () => setVisible(document.visibilityState === 'visible');
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
  }, []);

  useEffect(() => {
    const tick = () => setCountdown(formatCountdown(msUntil(nextRefreshAt)));
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [nextRefreshAt]);

  if (!sessionOpen || !visible) return null;

  return (
    <div
      className="flex items-center gap-2 rounded-full border border-[var(--color-surface-3)] bg-[var(--color-surface-2)]/90 px-2.5 py-1 shadow-sm"
      aria-live="polite"
      aria-label={`Live prices active. Next refresh in ${countdown}`}
    >
      <span className="relative flex h-2 w-2 shrink-0">
        <span
          className={`absolute inline-flex h-full w-full rounded-full bg-[var(--color-up)] opacity-75 ${
            isRefreshing ? 'animate-ping' : 'animate-pulse'
          }`}
        />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-[var(--color-up)]" />
      </span>
      <span className="font-display text-[length:var(--text-label)] font-semibold uppercase tracking-[0.12em] text-[var(--color-text-primary)]">
        Live
      </span>
      <span className="font-mono text-[length:var(--text-label)] tabular-nums text-[var(--color-text-muted)]">
        {countdown}
      </span>
    </div>
  );
}
