import { usePrivacyMode } from '../privacy';

/** Eye control: open = values visible, crossed = privacy on. */
export function PrivacyToggle() {
  const { privacyMode, togglePrivacyMode } = usePrivacyMode();

  return (
    <button
      type="button"
      onClick={togglePrivacyMode}
      aria-pressed={privacyMode}
      aria-label={privacyMode ? 'Show values' : 'Hide values'}
      title={privacyMode ? 'Show values' : 'Hide values'}
      className="desk-header__icon-btn desk-press"
    >
      {privacyMode ? <EyeOffIcon /> : <EyeIcon />}
    </button>
  );
}

function EyeIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinejoin="round"
      />
      <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.75" />
    </svg>
  );
}

function EyeOffIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M3 3l18 18M10.5 10.7a3 3 0 0 0 4.2 4.2M9.4 5.5A10.4 10.4 0 0 1 12 5c6.5 0 10 7 10 7a18.4 18.4 0 0 1-3.2 3.8M6.2 6.2A18.5 18.5 0 0 0 2 12s3.5 7 10 7c1.3 0 2.5-.3 3.6-.7"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
