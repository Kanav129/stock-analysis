import { useState, type FormEvent } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { isLoggedIn, setAuthSession } from '../auth';
import { useBackendWake } from '../hooks/useBackendWake';
import { LoadingSpinner } from '../components/LoadingSpinner';

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from || '/';
  const wakeStatus = useBackendWake();

  const [key, setKey] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<'key' | 'guest' | null>(null);

  if (isLoggedIn()) {
    return <Navigate to={from} replace />;
  }

  const wakeLabel =
    wakeStatus === 'ready'
      ? 'Desk ready'
      : wakeStatus === 'slow'
        ? 'Taking longer than usual — try signing in anyway'
        : 'Waking desk…';

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = key.trim();
    if (!trimmed) {
      setError('Enter your access key');
      return;
    }
    setPending('key');
    setError(null);
    try {
      const result = await api.login(trimmed);
      setAuthSession(trimmed, result.role === 'guest' ? 'guest' : 'admin');
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Invalid access key');
    } finally {
      setPending(null);
    }
  }

  async function onGuest() {
    setPending('guest');
    setError(null);
    try {
      const result = await api.guestLogin();
      setAuthSession(result.token, 'guest');
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not continue as guest');
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden px-4">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            'radial-gradient(ellipse 80% 60% at 50% -10%, color-mix(in oklch, var(--color-accent) 22%, transparent), transparent 55%), radial-gradient(ellipse 50% 40% at 80% 100%, color-mix(in oklch, var(--color-surface-3) 80%, transparent), transparent), var(--color-surface-0)',
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.04]"
        style={{
          backgroundImage:
            'linear-gradient(var(--color-text-primary) 1px, transparent 1px), linear-gradient(90deg, var(--color-text-primary) 1px, transparent 1px)',
          backgroundSize: '48px 48px',
        }}
      />

      <div className="relative w-full max-w-sm animate-fade-up">
        <p className="font-display text-[length:var(--text-label)] uppercase tracking-[0.2em] text-[var(--color-text-muted)]">
          Personal Desk
        </p>
        <h1 className="font-display font-display-title mt-1 text-3xl font-semibold text-[var(--color-text-primary)]">
          Stock Analysis
        </h1>
        <p className="mt-2 text-sm text-[var(--color-text-secondary)]">
          Enter your access key to open the desk.
        </p>

        <form onSubmit={onSubmit} className="mt-8 flex flex-col gap-3">
          <label className="sr-only" htmlFor="access-key">
            Access key
          </label>
          <input
            id="access-key"
            type="password"
            autoComplete="current-password"
            autoFocus
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="Access key"
            disabled={pending != null}
            className="w-full rounded border border-[var(--color-surface-3)] bg-[var(--color-surface-1)] px-3 py-2.5 font-mono text-sm text-[var(--color-text-primary)] outline-none placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent)]"
          />
          {error && (
            <p className="text-xs text-[var(--color-down)]" role="alert">
              {error}
            </p>
          )}
          <button type="submit" disabled={pending != null} className="btn-terminal btn-terminal--accent mt-1 flex w-full items-center justify-center gap-2">
            {pending === 'key' ? (
              <>
                <LoadingSpinner size="sm" />
                Checking…
              </>
            ) : (
              'Enter desk'
            )}
          </button>
        </form>

        <div className="mt-5 flex items-center gap-3" aria-hidden="true">
          <span className="h-px flex-1 bg-[var(--color-surface-3)]" />
          <span className="text-[length:var(--text-label)] uppercase tracking-[0.14em] text-[var(--color-text-muted)]">
            or
          </span>
          <span className="h-px flex-1 bg-[var(--color-surface-3)]" />
        </div>

        <button
          type="button"
          disabled={pending != null}
          onClick={() => void onGuest()}
          className="btn-terminal mt-4 flex w-full items-center justify-center gap-2"
        >
          {pending === 'guest' ? (
            <>
              <LoadingSpinner size="sm" />
              Opening…
            </>
          ) : (
            'Continue as guest'
          )}
        </button>
        <p className="mt-2 text-center text-xs text-[var(--color-text-secondary)]">
          View stocks, watchlist, and reports. Portfolio values stay hidden.
        </p>

        <p
          className="mt-4 flex items-center justify-center gap-2 text-center text-xs text-[var(--color-text-muted)]"
          aria-live="polite"
        >
          {wakeStatus !== 'ready' ? <LoadingSpinner size="sm" /> : null}
          {wakeLabel}
        </p>
      </div>
    </div>
  );
}
