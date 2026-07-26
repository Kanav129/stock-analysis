import type { ReactNode } from 'react';
import { usePrivacyMode } from '../privacy';

export const PRIVACY_MASK = '••••';

/** Renders a fixed mask when privacy mode is on; otherwise shows children. */
export function SensitiveValue({
  children,
  className = '',
}: {
  children: ReactNode;
  className?: string;
}) {
  const { privacyMode } = usePrivacyMode();
  if (privacyMode) {
    return (
      <span className={`font-mono text-[var(--color-text-muted)] ${className}`.trim()} aria-label="Hidden">
        {PRIVACY_MASK}
      </span>
    );
  }
  return <>{children}</>;
}
