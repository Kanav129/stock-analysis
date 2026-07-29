/** Shared loading indicator — accent ring spinner used across pages and charts. */

type SpinnerSize = 'sm' | 'md' | 'lg';

const SIZE_PX: Record<SpinnerSize, number> = {
  sm: 18,
  md: 28,
  lg: 36,
};

export function LoadingSpinner({
  size = 'md',
  className = '',
}: {
  size?: SpinnerSize;
  className?: string;
}) {
  const px = SIZE_PX[size];
  return (
    <svg
      width={px}
      height={px}
      viewBox="0 0 24 24"
      fill="none"
      stroke="var(--color-accent)"
      strokeWidth="2"
      className={className}
      style={{ animation: 'spin 1s linear infinite' }}
      role="presentation"
      aria-hidden
    >
      <circle cx="12" cy="12" r="10" strokeOpacity="0.2" />
      <path d="M12 2a10 10 0 0 1 10 10" strokeLinecap="round" />
    </svg>
  );
}

export function LoadingState({
  label,
  size = 'md',
  minHeight,
  compact = false,
  className = '',
}: {
  label?: string;
  size?: SpinnerSize;
  minHeight?: string | number;
  /** Tighter padding for inline panel rows. */
  compact?: boolean;
  className?: string;
}) {
  const style = minHeight != null
    ? { minHeight: typeof minHeight === 'number' ? `${minHeight}px` : minHeight }
    : undefined;

  return (
    <div
      className={`flex flex-col items-center justify-center gap-2 ${
        compact ? 'py-4' : 'py-8'
      } ${className}`}
      style={style}
      role="status"
      aria-busy="true"
      aria-label={label ?? 'Loading'}
    >
      <LoadingSpinner size={size} />
      {label ? (
        <p className="text-xs text-[var(--color-text-muted)]">{label}</p>
      ) : null}
    </div>
  );
}

/** Standard chart / lazy-route loading placeholder. */
export function ChartLoading({ label = 'Loading chart…' }: { label?: string }) {
  return <LoadingState label={label} minHeight="16rem" />;
}
