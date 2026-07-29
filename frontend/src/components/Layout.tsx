import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { clearAuthToken } from '../auth';
import { LivePriceProvider } from '../context/LivePriceContext';
import { useSyncKeepAlive } from '../hooks/useSyncKeepAlive';
import { LiveSessionIndicator } from './LiveSessionIndicator';
import { PrivacyToggle } from './PrivacyToggle';
import { clearDeskCache } from '../lib/deskCache';

const nav = [
  { to: '/', label: 'Desk' },
  { to: '/watchlist', label: 'Watchlist' },
  { to: '/settings', label: 'Settings' },
];

export function Layout() {
  const location = useLocation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  useSyncKeepAlive();

  function logout() {
    clearAuthToken();
    clearDeskCache();
    qc.clear();
    navigate('/login', { replace: true });
  }

  return (
    <LivePriceProvider>
      <div className="min-h-screen bg-[var(--color-surface-0)]">
        <header className="sticky top-0 z-20 border-b border-[var(--color-surface-3)] bg-[var(--color-surface-1)]/95 backdrop-blur-sm">
          <div className="terminal-shell relative mx-auto flex items-center justify-between gap-4 px-4 py-2.5">
            <div className="flex min-w-0 items-center gap-3">
              <div>
                <p className="font-display text-[length:var(--text-label)] uppercase tracking-[0.18em] text-[var(--color-text-muted)]">
                  Personal Desk
                </p>
                <h1 className="font-display text-base font-semibold leading-tight text-[var(--color-text-primary)]">
                  Stock Analysis
                </h1>
              </div>
            </div>
            <div className="pointer-events-none absolute inset-x-0 flex justify-center">
              <LiveSessionIndicator />
            </div>
            <nav className="flex items-center gap-0.5">
            {nav.map((item) => {
              const active = location.pathname === item.to;
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  className={`rounded px-2.5 py-1.5 text-xs font-semibold transition-colors ${
                    active
                      ? 'bg-[var(--color-surface-3)] text-[var(--color-text-primary)]'
                      : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]'
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <div className="flex items-center gap-1">
            <PrivacyToggle />
            <button
              type="button"
              onClick={logout}
              className="rounded px-2.5 py-1.5 text-xs font-semibold text-[var(--color-text-muted)] transition-colors hover:text-[var(--color-text-primary)]"
            >
              Log out
            </button>
          </div>
        </div>
      </header>
      <main className="terminal-shell mx-auto min-h-[70vh] px-4 py-4">
        <Outlet />
      </main>
    </div>
    </LivePriceProvider>
  );
}
