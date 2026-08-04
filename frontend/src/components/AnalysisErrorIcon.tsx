export function AnalysisErrorIcon({
  analysisFailed,
  analysisError,
  failedAt,
}: {
  analysisFailed?: boolean;
  analysisError?: string | null;
  failedAt?: string | null;
}) {
  if (!analysisFailed) return null;

  const title = analysisError ?? 'Latest analysis failed';
  const failedAtLabel = failedAt ? new Date(failedAt).toLocaleString() : null;
  const ariaLabel =
    failedAtLabel && failedAtLabel !== 'Invalid Date'
      ? `${title} at ${failedAtLabel}`
      : title;

  return (
    <span
      role="img"
      aria-label={ariaLabel}
      title={title}
      className="inline-flex shrink-0 text-[var(--color-down)]"
    >
      <svg
        width="14"
        height="14"
        viewBox="0 0 16 16"
        fill="none"
        aria-hidden="true"
      >
        <path
          d="M8 1.75 14.25 13H1.75L8 1.75Z"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinejoin="round"
        />
        <path
          d="M8 5.25v4"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinecap="round"
        />
        <circle cx="8" cy="11.5" r=".75" fill="currentColor" />
      </svg>
    </span>
  );
}
