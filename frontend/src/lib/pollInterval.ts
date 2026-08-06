/**
 * Shared desk polling helpers.
 * Hot status queries are owned by `useSyncKeepAlive` — other components should
 * subscribe to the same queryKey without their own refetchInterval.
 */

/** Active sync / jobs / analysis progress. */
export const POLL_ACTIVE_MS = 5_000;

/** Idle desk status refresh. */
export const POLL_IDLE_MS = 60_000;

/** Short cache so remounts don't immediately refetch. */
export const POLL_STALE_MS = 5_000;

export function isDocumentVisible(): boolean {
  return typeof document === 'undefined' || document.visibilityState === 'visible';
}

/** Return interval ms, or false when the tab is hidden (stops background polls). */
export function visiblePollInterval(ms: number | false): number | false {
  if (ms === false) return false;
  return isDocumentVisible() ? ms : false;
}
