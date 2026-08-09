import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { clearAuthToken } from '../auth';
import { LivePriceProvider } from '../context/LivePriceContext';
import { useSyncKeepAlive } from '../hooks/useSyncKeepAlive';
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
        <header className="desk-header">
          <div className="terminal-shell desk-header__shell">
            <div className="desk-header__bar">
              <div className="desk-header__brand">
                <p className="desk-header__eyebrow">Personal Desk</p>
                <h1 className="desk-header__title">Stock Analysis</h1>
              </div>

              <nav className="desk-header__nav" aria-label="Primary">
                {nav.map((item) => {
                  const active =
                    item.to === '/'
                      ? location.pathname === '/'
                      : location.pathname.startsWith(item.to);
                  return (
                    <Link
                      key={item.to}
                      to={item.to}
                      className={`desk-header__nav-link desk-press${active ? ' is-active' : ''}`}
                      aria-current={active ? 'page' : undefined}
                    >
                      {item.label}
                    </Link>
                  );
                })}
              </nav>

              <div className="desk-header__actions">
                <PrivacyToggle />
                <button type="button" onClick={logout} className="desk-header__logout desk-press">
                  Log out
                </button>
              </div>
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
