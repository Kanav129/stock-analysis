import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Layout } from './components/Layout';
import { RequireAuth } from './components/RequireAuth';
import { PageFallback } from './components/Skeleton';
import { PrivacyModeProvider } from './privacy';

const DashboardPage = lazy(() =>
  import('./pages/DashboardPage').then((m) => ({ default: m.DashboardPage })),
);
const StockDetailPage = lazy(() =>
  import('./pages/StockDetailPage').then((m) => ({ default: m.StockDetailPage })),
);
const WatchlistPage = lazy(() =>
  import('./pages/WatchlistPage').then((m) => ({ default: m.WatchlistPage })),
);
const SettingsPage = lazy(() =>
  import('./pages/SettingsPage').then((m) => ({ default: m.SettingsPage })),
);
const ResearchReportPage = lazy(() =>
  import('./pages/ResearchReportPage').then((m) => ({ default: m.ResearchReportPage })),
);
const LoginPage = lazy(() =>
  import('./pages/LoginPage').then((m) => ({ default: m.LoginPage })),
);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      gcTime: 10 * 60_000,
      retry: 1,
      refetchOnWindowFocus: false,
      refetchOnReconnect: true,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <PrivacyModeProvider>
        <BrowserRouter>
          <Routes>
          <Route
            path="/login"
            element={
              <Suspense fallback={<PageFallback />}>
                <LoginPage />
              </Suspense>
            }
          />
          <Route
            element={
              <RequireAuth>
                <Layout />
              </RequireAuth>
            }
          >
            <Route
              path="/"
              element={
                <Suspense fallback={<PageFallback />}>
                  <DashboardPage />
                </Suspense>
              }
            />
            <Route
              path="/stock/:ticker"
              element={
                <Suspense fallback={<PageFallback />}>
                  <StockDetailPage />
                </Suspense>
              }
            />
            <Route
              path="/stock/:ticker/report"
              element={
                <Suspense fallback={<PageFallback />}>
                  <ResearchReportPage />
                </Suspense>
              }
            />
            <Route
              path="/watchlist"
              element={
                <Suspense fallback={<PageFallback />}>
                  <WatchlistPage />
                </Suspense>
              }
            />
            <Route
              path="/settings"
              element={
                <Suspense fallback={<PageFallback />}>
                  <SettingsPage />
                </Suspense>
              }
            />
          </Route>
        </Routes>
      </BrowserRouter>
      </PrivacyModeProvider>
    </QueryClientProvider>
  );
}
