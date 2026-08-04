import { useEffect, useState } from 'react';
import { useLivePrice } from '../context/LivePriceContext';
import { formatCountdown, msUntil } from '../lib/livePriceSchedule';
import { isUsRegularSession } from '../lib/usMarketHours';

/**
 * Desk header badge: live pulse + countdown during US RTH, otherwise "Not Live".
 */
export function LiveSessionIndicator() {
  const { nextRefreshAt, pausedUntil, isRefreshing } = useLivePrice();
  const [sessionOpen, setSessionOpen] = useState(() => isUsRegularSession());
  const [countdown, setCountdown] = useState(() => formatCountdown(msUntil(nextRefreshAt)));

  useEffect(() => {
    const syncSession = () => setSessionOpen(isUsRegularSession());
    syncSession();
    const id = window.setInterval(syncSession, 30_000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (!sessionOpen) return;
    const tick = () => {
      const paused = pausedUntil != null && Date.now() < pausedUntil;
      const target = paused ? pausedUntil : nextRefreshAt;
      setCountdown(formatCountdown(msUntil(target)));
    };
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [nextRefreshAt, pausedUntil, sessionOpen]);

  const isPaused = pausedUntil != null && Date.now() < pausedUntil;

  if (sessionOpen && isPaused) {
    return (
      <div
        className="flex items-center gap-2 rounded-full border border-[var(--color-surface-3)] bg-[var(--color-surface-2)]/90 px-2.5 py-1 shadow-sm"
        aria-live="polite"
        aria-label={`Live prices paused (Yahoo rate limit). Resumes in ${countdown}`}
      >
        <span className="inline-flex h-2 w-2 shrink-0 rounded-full bg-amber-500" />
        <span className="font-display text-[length:var(--text-label)] font-semibold uppercase tracking-[0.12em] text-[var(--color-text-primary)]">
          Paused
        </span>
        <span className="font-mono text-[length:var(--text-label)] tabular-nums text-[var(--color-text-muted)]">
          {countdown}
        </span>
      </div>
    );
  }

  if (sessionOpen) {
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

  return (
    <div
      className="flex items-center gap-2 rounded-full border border-[var(--color-surface-3)] bg-[var(--color-surface-2)]/90 px-2.5 py-1 shadow-sm"
      aria-live="polite"
      aria-label="Live prices inactive. US market is closed."
    >
      <span className="inline-flex h-2 w-2 shrink-0 rounded-full bg-[var(--color-down)]" />
      <span className="font-display text-[length:var(--text-label)] font-semibold uppercase tracking-[0.12em] text-[var(--color-text-primary)]">
        Not Live
      </span>
    </div>
  );
}
