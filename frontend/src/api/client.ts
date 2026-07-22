import { clearAuthToken, getAuthToken } from '../auth';

/** Local Vite proxies `/api` → backend. Production uses full Render URL. */
const BASE = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '');

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options?.headers as Record<string, string> | undefined),
  };
  const token = getAuthToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers,
  });

  if (res.status === 401) {
    clearAuthToken();
    if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
      window.location.assign('/login');
    }
    const err = await res.json().catch(() => ({ detail: 'Unauthorized' }));
    throw new Error(formatApiError(err, 'Unauthorized'));
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(formatApiError(err, `${res.status} ${res.statusText}`));
  }
  return res.json();
}

function formatApiError(err: { detail?: unknown }, fallback: string): string {
  const detail = err?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (typeof item === 'string') return item;
      if (item && typeof item === 'object' && 'msg' in item) {
        const loc = Array.isArray((item as { loc?: unknown }).loc)
          ? (item as { loc: unknown[] }).loc.join('.')
          : '';
        const msg = String((item as { msg: unknown }).msg);
        return loc ? `${loc}: ${msg}` : msg;
      }
      return JSON.stringify(item);
    });
    return parts.filter(Boolean).join('; ') || fallback;
  }
  if (detail && typeof detail === 'object') return JSON.stringify(detail);
  return fallback;
}

export const api = {
  getAuthStatus: () => request<{ auth_required: boolean }>('/auth/status'),
  login: (key: string) =>
    request<{ ok: boolean; auth_required: boolean }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ key }),
    }),
  getHoldings: () => request<{ holdings: import('./types').Holding[]; summary: import('./types').PortfolioSummary }>('/holdings'),
  getRatings: () => request<{ ratings: import('./types').StockRating[] }>('/ratings'),
  getRatingHistory: (ticker: string) => request<{ ticker: string; history: import('./types').StockRating[] }>(`/ratings/${ticker}`),
  runAnalysis: (tickers?: string[], opts?: { force?: boolean }) =>
    request<import('./types').AnalysisProgress>('/analysis/run', {
      method: 'POST',
      body: JSON.stringify({ tickers: tickers ?? null, force: Boolean(opts?.force) }),
    }),
  rescoreAnalysis: (tickers?: string[]) =>
    request<import('./types').AnalysisProgress>('/analysis/rescore', {
      method: 'POST',
      body: JSON.stringify({ tickers: tickers ?? null }),
    }),
  cancelAnalysis: () => request<import('./types').AnalysisProgress>('/analysis/cancel', { method: 'POST' }),
  syncData: (tickers?: string[], opts?: { force?: boolean }) => request<{ started: boolean; message: string; tickers: string[]; last_sync?: string; errors?: { stage: string; error: string }[] }>('/sync/data', {
    method: 'POST',
    body: JSON.stringify({ tickers: tickers ?? null, force: Boolean(opts?.force) }),
  }),
  getSyncStatus: () => request<import('./types').SyncProgress>('/sync/status'),
  /** Unauthenticated; used to keep the Render free dyno awake during long syncs. */
  health: () => request<{ status: string }>('/health'),
  getAnalysisStatus: () => request<import('./types').AnalysisProgress>('/analysis/status'),
  getWatchlist: () => request<{ items: import('./types').WatchlistItem[] }>('/watchlist'),
  addWatchlist: (ticker: string, notes?: string) => request<import('./types').WatchlistItem>('/watchlist', {
    method: 'POST',
    body: JSON.stringify({ ticker, notes }),
  }),
  removeWatchlist: (ticker: string) => request<{ removed: string }>(`/watchlist/${ticker}`, { method: 'DELETE' }),
  getUniverse: () => request<{ tickers: string[]; watchlist: string[]; holdings: string[] }>('/universe'),
  getChart: (ticker: string, priceType = 'close', duration = '30') =>
    request<{ ticker: string; result: import('./types').ChartPoint[] }>(`/stock/${ticker}/chart?price_type=${priceType}&duration=${duration}`),
  getQuotes: (tickers: string[], sparkDays = 30) =>
    request<{ quotes: Record<string, import('./types').StockQuote> }>(
      `/stock/quotes?tickers=${encodeURIComponent(tickers.join(','))}&spark_days=${sparkDays}`,
    ),
  getTechnicals: (ticker: string) =>
    request<import('./types').StockTechnicals>(`/stock/${ticker}/technicals`),
  getRecentNews: (ticker: string, limit = 10) =>
    request<{ ticker: string; articles: import('./types').NewsArticle[] }>(`/news/${ticker}/articles?limit=${limit}`),
  getSettings: () => request<Record<string, string>>('/settings'),
  updateSettings: (data: Record<string, string | number>) => request<Record<string, string>>('/settings', {
    method: 'PUT',
    body: JSON.stringify(data),
  }),
  getOpenRouterStatus: () =>
    request<{
      connected: boolean;
      message: string;
      low_balance?: boolean;
      key?: {
        label?: string;
        limit?: number | null;
        limit_remaining?: number | null;
        limit_reset?: string | null;
        usage?: number;
        usage_daily?: number;
        usage_weekly?: number;
        usage_monthly?: number;
        is_free_tier?: boolean;
      } | null;
      credits?: {
        total_credits?: number;
        total_usage?: number;
        remaining?: number | null;
      } | null;
      credits_note?: string | null;
    }>('/settings/openrouter'),
  generateReport: (ticker: string) => request<{ task_id: string; status: string }>(`/research/${ticker}`, { method: 'POST' }),
  generateDeepReport: (ticker: string) => request<{ task_id: string; status: string }>(`/research/${ticker}/deep`, { method: 'POST' }),
  getReport: (ticker: string, type: string = 'core') => request<import('./types').ResearchReport>(`/research/${ticker}?type=${type}`),
  getTaskStatus: (taskId: string) => request<import('./types').ReportTask>(`/research/task/${taskId}`),
  getActiveReportTask: (ticker: string) =>
    request<{ task: import('./types').ReportTask | null }>(`/research/${ticker}/active`),
  getReportHistory: (ticker: string) => request<{ ticker: string; items: import('./types').ReportHistoryItem[] }>(`/research/${ticker}/history`),
};
