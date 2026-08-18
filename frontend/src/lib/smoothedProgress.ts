/** Time-based progress that tracks an estimated duration, then decelerates if late. */

export const DEFAULT_CORE_SECONDS = 190;
export const DEFAULT_DEEP_SECONDS = 240;

export function estimateSecondsForJobType(
  jobType: string,
  estimates?: { core_analysis?: number; deep_dive?: number } | null,
): number {
  if (jobType === 'deep_dive') {
    const n = Number(estimates?.deep_dive);
    return Number.isFinite(n) && n > 0 ? n : DEFAULT_DEEP_SECONDS;
  }
  const n = Number(estimates?.core_analysis);
  return Number.isFinite(n) && n > 0 ? n : DEFAULT_CORE_SECONDS;
}

export function smoothedProgressPercent({
  elapsedMs,
  estimatedMs,
  complete,
}: {
  elapsedMs: number;
  estimatedMs: number;
  complete: boolean;
}): number {
  if (complete) return 100;
  if (!(elapsedMs > 0) || !(estimatedMs > 0)) return 0;
  const t = elapsedMs / estimatedMs;
  if (t < 0.9) {
    return Math.max(0, Math.min(100, t * 100));
  }
  const display = 90 + 9 * (1 - Math.exp(-(t - 0.9) / 0.35));
  return Math.min(99, display);
}
