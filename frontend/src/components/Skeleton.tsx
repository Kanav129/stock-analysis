/** Lightweight loading placeholders — reserve space to avoid CLS. */
import type { CSSProperties } from 'react';

export function Skeleton({
  className = '',
  style,
}: {
  className?: string;
  style?: CSSProperties;
}) {
  return <div className={`skeleton ${className}`} style={style} aria-hidden />;
}

export function DeskSkeleton() {
  return (
    <div className="flex flex-col gap-3" aria-busy="true" aria-label="Loading trading desk">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-2">
          <Skeleton className="h-5 w-36" />
          <Skeleton className="h-3 w-48" />
        </div>
        <div className="flex gap-2">
          <Skeleton className="h-8 w-36" />
          <Skeleton className="h-8 w-32" />
        </div>
      </div>

      <div className="rounded-[var(--panel-radius)] border border-[var(--color-surface-3)] bg-[var(--color-surface-1)] p-3">
        <Skeleton className="mb-2 h-3 w-28" />
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-[58px] w-full rounded" />
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-16 w-full rounded" />
        ))}
      </div>

      <div className="terminal-grid">
        <div className="col-span-12 lg:col-span-8">
          <div className="rounded-[var(--panel-radius)] border border-[var(--color-surface-3)] bg-[var(--color-surface-1)] p-3">
            <Skeleton className="mb-3 h-3 w-24" />
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="mb-2 h-8 w-full" />
            ))}
          </div>
        </div>
        <div className="col-span-12 flex flex-col gap-3 lg:col-span-4">
          <div className="rounded-[var(--panel-radius)] border border-[var(--color-surface-3)] bg-[var(--color-surface-1)] p-3">
            <Skeleton className="mb-2 h-3 w-32" />
            <div className="grid grid-cols-2 gap-1.5">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-14 w-full rounded" />
              ))}
            </div>
          </div>
          <div className="rounded-[var(--panel-radius)] border border-[var(--color-surface-3)] bg-[var(--color-surface-1)] p-3">
            <Skeleton className="mb-2 h-3 w-28" />
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="mb-2 h-7 w-full" />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export function PageFallback() {
  return (
    <div className="flex flex-col gap-3 py-2" aria-busy="true" aria-label="Loading page">
      <Skeleton className="h-6 w-40" />
      <Skeleton className="h-3 w-64" />
      <Skeleton className="mt-2 h-40 w-full rounded" />
      <Skeleton className="h-24 w-full rounded" />
    </div>
  );
}
