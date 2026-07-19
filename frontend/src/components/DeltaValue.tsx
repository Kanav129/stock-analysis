/** Colored +/- percentage or absolute delta. */
export function DeltaValue({
  value,
  suffix = '%',
  className = '',
}: {
  value: number | null | undefined;
  suffix?: string;
  className?: string;
}) {
  if (value == null || Number.isNaN(value)) {
    return <span className={`font-mono text-[var(--color-text-muted)] ${className}`}>—</span>;
  }
  const up = value > 0;
  const flat = value === 0;
  const color = flat
    ? 'text-[var(--color-text-muted)]'
    : up
      ? 'text-[var(--color-up)]'
      : 'text-[var(--color-down)]';
  const sign = up ? '+' : '';
  return (
    <span className={`font-mono tabular-nums ${color} ${className}`}>
      {sign}{value.toFixed(2)}{suffix}
    </span>
  );
}
