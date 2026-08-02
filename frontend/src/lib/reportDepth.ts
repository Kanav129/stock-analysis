import type { ReportType } from '../api/types';

/** Normalize API/report provenance for quiet deep vs core styling. */
export function normalizeReportDepth(
  value: string | null | undefined,
): ReportType | null {
  if (value === 'deep' || value === 'core') return value;
  return null;
}

export function isDeepReport(value: string | null | undefined): boolean {
  return normalizeReportDepth(value) === 'deep';
}

/** Plain ±score text beside a badge (Calls / Recent rows). */
export function scoreTextClass(depth: string | null | undefined): string {
  return isDeepReport(depth)
    ? 'font-mono text-xs font-semibold tabular-nums text-[var(--color-text-primary)]'
    : 'font-mono text-xs tabular-nums text-[var(--color-text-secondary)]';
}
