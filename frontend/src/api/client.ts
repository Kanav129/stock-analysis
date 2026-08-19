import { clearAuthToken, getAuthToken } from '../auth';

/** Local Vite proxies `/api` → backend. Production uses full Render URL. */
const BASE = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '');

export type LlmUsageBucket = {
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
};

export type LlmUsagePeriod = {
  total: LlmUsageBucket;
  analysis: LlmUsageBucket;
  research: LlmUsageBucket;
  other?: LlmUsageBucket;
};

export type LlmUsageDaily = {
  date: string;
  analysis_cost: number;
  research_cost: number;
  other_cost?: number;
  total_cost: number;
  analysis_tokens: number;
  research_tokens: number;
  other_tokens?: number;
  total_tokens: number;
};

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
    if (res.status === 502 || res.status === 503 || res.status === 504) {
      throw new Error(
        'API unreachable (Bad Gateway). Start local uvicorn on port 8001, then refresh.',
      );
    }
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(formatApiError(err, `${res.status} ${res.statusText}`));
  }
  return res.json();
}

/** Like `request`, but returns null on 404 instead of throwing. */
async function requestOptional<T>(path: string, options?: RequestInit): Promise<T | null> {
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

  if (res.status === 404) return null;

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
    request<{ ok: boolean; auth_required: boolean; role?: 'admin' | 'guest' }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ key }),
    }),
  guestLogin: () =>
    request<{ ok: boolean; auth_required: boolean; role: 'guest'; token: string }>('/auth/guest', {
      method: 'POST',
    }),
  getDeskSnapshot: () =>
    request<import('./types').DeskSnapshot>('/desk/snapshot'),
  getHoldings: () =>
    request<{
      holdings: import('./types').Holding[];
      summary: import('./types').PortfolioSummary;
      holdings_synced_at?: string | null;
      source?: string | null;
    }>('/holdings'),
  syncHoldings: () =>
    request<import('./types').HoldingsSyncResult>('/holdings/sync', {
      method: 'POST',
      body: JSON.stringify({}),
    }),
  getRatings: (tickers?: string[]) => {
    const qs =
      tickers && tickers.length
        ? `?tickers=${encodeURIComponent(tickers.join(','))}`
        : '';
    return request<{ ratings: import('./types').StockRating[] }>(`/ratings${qs}`);
  },
  getRecentRatings: async (limit = 8) => {
    const data = await request<{
      ratings?: import('./types').StockRating[];
      ticker?: string;
      history?: unknown;
    }>(`/ratings/recent?limit=${encodeURIComponent(String(limit))}`);
    if (Array.isArray(data?.ratings)) {
      return { ratings: data.ratings };
    }
    // Stale API: /ratings/{ticker} captured "recent" before /ratings/recent existed.
    if (
      typeof data?.ticker === 'string' &&
      data.ticker.toUpperCase() === 'RECENT' &&
      Array.isArray(data?.history)
    ) {
      throw new Error(
        'Stale API on port 8001 — GET /ratings/recent is missing. Stop Docker/OrbStack on :8001, then run: uvicorn rest_api.main:app --reload --host 0.0.0.0 --port 8001',
      );
    }
    throw new Error(
      'Recent analysis endpoint unavailable. Restart the API (or redeploy) so GET /ratings/recent is registered.',
    );
  },
  getRatingHistory: (ticker: string) => request<{ ticker: string; history: import('./types').StockRating[] }>(`/ratings/${ticker}`),
  runAnalysis: (tickers?: string[], opts?: { force?: boolean }) =>
    request<import('./types').AnalysisProgress>('/analysis/run', {
      method: 'POST',
      body: JSON.stringify({ tickers: tickers ?? null, force: Boolean(opts?.force) }),
    }),
  retryFailedAnalysis: () =>
    request<
      Partial<import('./types').AnalysisProgress> & {
        tickers: string[];
        running: boolean;
        message: string;
      }
    >('/analysis/retry-failed', {
      method: 'POST',
    }),
  rescoreAnalysis: (tickers?: string[]) =>
    request<import('./types').AnalysisProgress>('/analysis/rescore', {
      method: 'POST',
      body: JSON.stringify({ tickers: tickers ?? null }),
    }),
  cancelAnalysis: () => request<import('./types').AnalysisProgress>('/analysis/cancel', { method: 'POST' }),
  syncData: (tickers?: string[], opts?: { force?: boolean }) =>
    request<import('./types').SyncStartResponse>('/sync/data', {
      method: 'POST',
      body: JSON.stringify({ tickers: tickers ?? null, force: Boolean(opts?.force) }),
    }),
  getSyncStatus: () => request<import('./types').SyncProgress>('/sync/status'),
  cancelSync: () => request<import('./types').SyncProgress>('/sync/cancel', { method: 'POST' }),
  /** Unauthenticated; used to keep the Render free dyno awake during long syncs. */
  health: () => request<{ status: string }>('/health'),
  getAnalysisStatus: () => request<import('./types').AnalysisProgress>('/analysis/status'),
  getJobs: (opts?: { lite?: boolean }) => {
    const q = opts?.lite ? '?lite=1' : '';
    return request<import('./types').JobsSnapshot>(`/jobs${q}`);
  },
  enqueueJobs: (
    jobType: 'core_analysis' | 'deep_dive' | 'rescore',
    tickers?: string[],
    opts?: { force?: boolean },
  ) =>
    request<{
      started: boolean;
      message?: string;
      reason?: string;
      jobs?: import('./types').DeskJob[];
      enqueued?: import('./types').DeskJob[];
      reused?: import('./types').DeskJob[];
      limits?: import('./types').JobsSnapshot['limits'];
    }>('/jobs', {
      method: 'POST',
      body: JSON.stringify({
        job_type: jobType,
        tickers: tickers ?? null,
        force: Boolean(opts?.force),
      }),
    }),
  cancelJob: (jobId: string) =>
    request<{ ok: boolean; job?: import('./types').DeskJob }>(`/jobs/${jobId}/cancel`, {
      method: 'POST',
    }),
  cancelAllJobs: () =>
    request<{ ok: boolean; jobs?: import('./types').DeskJob[]; limits?: import('./types').JobsSnapshot['limits'] }>(
      '/jobs/cancel-all',
      { method: 'POST' },
    ),
  getWatchlist: () => request<{ items: import('./types').WatchlistItem[] }>('/watchlist'),
  addWatchlist: (ticker: string, notes?: string) => request<import('./types').WatchlistItem>('/watchlist', {
    method: 'POST',
    body: JSON.stringify({ ticker, notes }),
  }),
  removeWatchlist: (ticker: string) => request<{ removed: string }>(`/watchlist/${ticker}`, { method: 'DELETE' }),
  getWatchlistSuggestions: () =>
    request<{ items: import('./types').WatchlistSuggestion[] }>('/watchlist/suggestions'),
  getWatchlistSuggestion: (ticker: string) =>
    request<import('./types').WatchlistSuggestion>(
      `/watchlist/suggestions/${encodeURIComponent(ticker)}`,
    ),
  acceptWatchlistSuggestion: (ticker: string) =>
    request<{
      ticker: string;
      item: import('./types').WatchlistItem;
      job: unknown;
    }>('/watchlist/suggestions/accept', {
      method: 'POST',
      body: JSON.stringify({ ticker }),
    }),
  getUniverse: () => request<{ tickers: string[]; watchlist: string[]; holdings: string[] }>('/universe'),
  getChart: (ticker: string, priceType = 'close', duration = '30') =>
    request<{
      ticker: string;
      interval?: string;
      session_date?: string;
      result: import('./types').ChartPoint[];
    }>(`/stock/${ticker}/chart?price_type=${priceType}&duration=${duration}`),
  getQuotes: (tickers: string[], sparkDays = 30) =>
    request<{ quotes: Record<string, import('./types').StockQuote> }>(
      `/stock/quotes?tickers=${encodeURIComponent(tickers.join(','))}&spark_days=${sparkDays}`,
    ),
  livePriceRefresh: (tickers: string[]) =>
    request<{
      skipped: boolean;
      reason?: string;
      rate_limited?: boolean;
      pause_until?: string;
      results: Record<string, { upserted?: number; error?: string }>;
    }>('/stock/prices/live-refresh', {
      method: 'POST',
      body: JSON.stringify({ tickers }),
    }),
  getTechnicals: (ticker: string) =>
    request<import('./types').StockTechnicals>(`/stock/${ticker}/technicals`),
  getRecentNews: (ticker: string, limit = 10) =>
    request<{ ticker: string; articles: import('./types').NewsArticle[] }>(`/news/${ticker}/articles?limit=${limit}`),
  getSettings: () => request<Record<string, string>>('/settings'),
  updateSettings: (data: Record<string, string | number>) => request<Record<string, string>>('/settings', {
    method: 'PUT',
    body: JSON.stringify(data),
  }),
  getLlmStatus: () =>
    request<{
      connected: boolean;
      provider?: string;
      message: string;
      low_balance?: boolean;
      analysis_model?: string;
      research_model?: string;
      key?: {
        label?: string;
        models_available?: number;
      } | null;
      credits?: {
        remaining?: number | null;
        raw?: unknown;
      } | null;
      credits_note?: string | null;
    }>('/settings/llm'),
  getLlmUsage: (range: 'week' | 'month' = 'week') =>
    request<{
      currency: string;
      range: 'week' | 'month';
      note?: string;
      periods: {
        today: LlmUsagePeriod;
        week: LlmUsagePeriod;
        month: LlmUsagePeriod;
      };
      daily: LlmUsageDaily[];
    }>(`/settings/llm/usage?range=${range}`),
  /** @deprecated Use getLlmStatus */
  getOpenRouterStatus: () => api.getLlmStatus(),
  generateReport: (ticker: string) => request<{ task_id: string; status: string }>(`/research/${ticker}`, { method: 'POST' }),
  generateDeepReport: (ticker: string) => request<{ task_id: string; status: string }>(`/research/${ticker}/deep`, { method: 'POST' }),
  getReport: (ticker: string, type: string = 'latest') =>
    request<import('./types').ResearchReportEnvelope>(`/research/${ticker}?type=${type}`),
  /** Latest report by created_at (any type). Pass `core`/`deep` to filter. */
  getReportIfExists: async (ticker: string, type: string = 'latest') => {
    const envelope = await requestOptional<import('./types').ResearchReportEnvelope>(
      `/research/${ticker}?type=${type}`,
    );
    return envelope ?? {
      report: null,
      analysis_failed: false,
      analysis_error: null,
      failed_at: null,
    };
  },
  getTaskStatus: (taskId: string) => request<import('./types').ReportTask>(`/research/task/${taskId}`),
  getActiveReportTask: (ticker: string) =>
    request<{ task: import('./types').ReportTask | null }>(`/research/${ticker}/active`),
  getReportHistory: (ticker: string) =>
    request<{ ticker: string; items: import('./types').ReportHistoryItem[] }>(
      `/research/${ticker}/history`,
    ),
  downloadReportPdf: async (ticker: string, reportId: number) => {
    const headers: Record<string, string> = {};
    const token = getAuthToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    const res = await fetch(`${BASE}/research/${ticker}/reports/${reportId}/pdf`, {
      headers,
    });
    if (res.status === 401) {
      clearAuthToken();
      if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
        window.location.assign('/login');
      }
      throw new Error('Unauthorized');
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(formatApiError(err, `${res.status} ${res.statusText}`));
    }
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') || '';
    const match = /filename="([^"]+)"/i.exec(cd);
    const filename = match?.[1] || `${ticker.toUpperCase()}_report_${reportId}.pdf`;
    const url = URL.createObjectURL(blob);
    try {
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.rel = 'noopener';
      document.body.appendChild(a);
      a.click();
      a.remove();
    } finally {
      URL.revokeObjectURL(url);
    }
  },
};
