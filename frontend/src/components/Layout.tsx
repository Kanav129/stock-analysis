import { useEffect } from 'react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { clearAuthToken } from '../auth';

const nav = [
  { to: '/', label: 'Desk' },
  { to: '/watchlist', label: 'Watchlist' },
  { to: '/settings', label: 'Settings' },
];

export function Layout() {
  const location = useLocation();
  const navigate = useNavigate();
  const qc = useQueryClient();

  function logout() {
    clearAuthToken();
    qc.clear();
    navigate('/login', { replace: true });
  }

  // Warm the desk cache on first shell paint so returning home feels instant
  useEffect(() => {
    void qc.prefetchQuery({ queryKey: ['holdings'], queryFn: api.getHoldings, staleTime: 30_000 });
    void qc.prefetchQuery({ queryKey: ['ratings'], queryFn: api.getRatings, staleTime: 30_000 });
    void qc.prefetchQuery({ queryKey: ['watchlist'], queryFn: api.getWatchlist, staleTime: 60_000 });
    void qc.prefetchQuery({
      queryKey: ['quotes', 'market', 'SPY,QQQ,IWM,DIA'],
      queryFn: () => api.getQuotes(['SPY', 'QQQ', 'IWM', 'DIA'], 30),
      staleTime: 30_000,
    });
  }, [qc]);

  return (
    <div className="min-h-screen bg-[var(--color-surface-0)]">
      <header className="sticky top-0 z-20 border-b border-[var(--color-surface-3)] bg-[var(--color-surface-1)]/95 backdrop-blur-sm">
        <div className="terminal-shell mx-auto flex items-center justify-between gap-4 px-4 py-2.5">
          <div className="flex items-center gap-3 min-w-0">
            <div>
              <p className="font-display text-[10px] uppercase tracking-[0.18em] text-[var(--color-text-muted)]">
                Personal Desk
              </p>
              <h1 className="font-display text-base font-semibold leading-tight text-[var(--color-text-primary)]">
                Stock Analysis
              </h1>
            </div>
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
          <button
            type="button"
            onClick={logout}
            className="rounded px-2.5 py-1.5 text-xs font-semibold text-[var(--color-text-muted)] transition-colors hover:text-[var(--color-text-primary)]"
          >
            Log out
          </button>
        </div>
      </header>
      <main className="terminal-shell mx-auto min-h-[70vh] px-4 py-4">
        <Outlet />
      </main>
    </div>
  );
}
