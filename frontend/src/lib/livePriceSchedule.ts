/** Shared live price refresh cadence (must match LivePriceProvider). */
export const LIVE_REFRESH_INTERVAL_MS = 5 * 60_000;

export function formatCountdown(remainingMs: number): string {
  const totalSec = Math.max(0, Math.ceil(remainingMs / 1000));
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  return `${min}:${sec.toString().padStart(2, '0')}`;
}

export function msUntil(targetAt: number | null, now = Date.now()): number {
  if (targetAt == null) return LIVE_REFRESH_INTERVAL_MS;
  return Math.max(0, targetAt - now);
}
