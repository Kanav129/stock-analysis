export type Rating =
  | 'STRONG_SELL'
  | 'SELL'
  | 'REDUCE'
  | 'HOLD'
  | 'ACCUMULATE'
  | 'BUY'
  | 'STRONG_BUY';

/** Research report provenance for a rating/score. */
export type ReportType = 'core' | 'deep';

export interface StockRating {
  id: number;
  ticker: string;
  rating: Rating;
  /** Overall AI score: −100 strong sell … +100 strong buy */
  score: number;
  reasoning: string;
  key_drivers: string[];
  supporting_headlines: { headline: string }[];
  price_summary: Record<string, unknown>;
  model?: string;
  created_at: string;
  source?: string;
  /** Present when the rating came from a core/deep research report. */
  report_type?: ReportType | null;
}

export interface Holding {
  account_id: string;
  ticker: string;
  quantity: number;
  avg_cost: number | null;
  market_price: number | null;
  market_value: number | null;
  unrealized_pnl: number | null;
  currency: string;
  snapshot_at: string | null;
  price_date?: string | null;
  conid?: string | null;
  asset_class?: string | null;
  description?: string | null;
  ibkr_mark_price?: number | null;
  ibkr_position_value?: number | null;
  ibkr_unrealized_pnl?: number | null;
  percent_of_nav?: number | null;
  source?: string | null;
}

export interface HoldingsSyncResult {
  saved: number;
  skipped: number;
  tickers: string[];
  snapshot_at: string | null;
  source: string;
  skipped_asset_classes?: Record<string, number>;
}

export interface StockQuote {
  ticker: string;
  latest_close: number | null;
  prior_close: number | null;
  change_pct: number | null;
  spark: number[];
  as_of: string | null;
}

export interface StockTechnicals {
  ticker: string;
  available: boolean;
  latest_close?: number | null;
  rsi_14?: number | null;
  macd?: {
    macd_line: number;
    signal_line: number;
    histogram: number;
  };
  sma_20?: number | null;
  sma_50?: number | null;
  sma_200?: number | null;
  high_52w?: number | null;
  low_52w?: number | null;
  atr_14?: number | null;
  atr_pct?: number | null;
  as_of?: string | null;
}

export interface PortfolioSummary {
  total_value: number;
  total_unrealized_pnl: number;
  /** Weighted portfolio move vs prior daily closes. */
  day_change_pct?: number | null;
  day_change_value?: number | null;
  /** Unrealized P&L as % of cost basis. */
  overall_change_pct?: number | null;
  position_count: number;
  snapshot_at: string | null;
  /** When the holdings book was last imported (IBKR Flex / manual). */
  holdings_synced_at?: string | null;
  source?: string | null;
}

export interface WatchlistItem {
  id: number;
  ticker: string;
  notes: string | null;
  added_at: string;
  rating?: Rating | null;
  score?: number | null;
  report_type?: ReportType | null;
  latest_price?: number | null;
  price_date?: string | null;
  description?: string | null;
}

export interface ChartPoint {
  date: string;
  close?: number;
  open?: number;
  high?: number;
  low?: number;
  [key: string]: string | number | undefined;
}

export interface NewsArticle {
  headline: string;
  description: string;
  posted: string;
  source?: string;
  link?: string;
}

// ── Research report types ──

export interface ResearchReport {
  id: number;
  ticker: string;
  report_type: 'core' | 'deep';
  sections: Record<string, string>;
  rating: {
    rating: Rating;
    score: number;
    reasoning: string;
    key_drivers: string[];
    supporting_headlines: { headline: string }[];
    posture?: string;
    calibration_note?: string;
  } | null;
  factor_scores: Record<string, number> | null;
  entry_levels: {
    entry: number | null;
    stop: number | null;
    target: number | null;
    position_note: string;
  } | null;
  live_price: number | null;
  model: string | null;
  created_at: string;
}

export interface ReportTask {
  task_id: string;
  status: 'pending' | 'running' | 'done' | 'failed' | 'cancelled' | string;
  ticker: string;
  report_type: 'core' | 'deep';
  report_id: number | null;
  rating: Rating | null;
  score: number | null;
  error: string | null;
}

export interface ReportHistoryItem {
  id: number;
  ticker: string;
  report_type: 'core' | 'deep';
  created_at: string;
}

export interface ForecastPoint {
  day: number;
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface DailyRunSummary {
  date: string;
  timezone: string;
  status: string;
  can_resume: boolean;
  already_completed_today: boolean;
  news_done_count?: number;
  prices_done_count?: number;
  completed_count?: number;
  /** Watchlist/holdings universe size for progress denominators. */
  universe_count?: number;
  finished_at: string | null;
}

export interface DeskJob {
  id: string;
  job_type: 'core_analysis' | 'deep_dive' | 'rescore' | string;
  ticker: string;
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled' | 'interrupted' | string;
  cancel_requested?: boolean;
  progress: {
    stage?: string | null;
    stage_label?: string | null;
    message?: string | null;
    percent?: number | null;
  };
  result: {
    report_id?: number | null;
    rating?: string | null;
    score?: number | null;
  };
  error?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  updated_at?: string | null;
}

export interface JobsSnapshot {
  sync: SyncProgress | null;
  jobs: DeskJob[];
  limits: {
    max_concurrent: number;
    running: number;
    queued: number;
  };
}

export interface AnalysisProgress {
  running: boolean;
  status: 'idle' | 'pending' | 'running' | 'done' | 'failed' | 'cancelled';
  mode?: 'core_report' | 'rescore' | string;
  tickers: string[];
  total: number;
  current_index: number;
  current_ticker: string | null;
  stage: string | null;
  stage_label: string | null;
  completed: { ticker: string; rating?: string; score?: number; report_id?: number }[];
  errors: { ticker: string; error: string }[];
  percent: number;
  message: string;
  started_at: string | null;
  finished_at: string | null;
  last_run: string | null;
  started?: boolean;
  daily?: DailyRunSummary;
}

export interface SyncProgress {
  running: boolean;
  status: 'idle' | 'running' | 'completed' | 'error' | string;
  tickers: string[];
  total: number;
  current_index: number;
  current_ticker: string | null;
  stage: string | null;
  stage_label: string | null;
  completed: string[];
  errors: { ticker: string; error: string }[];
  percent: number;
  message: string | null;
  /** Live sub-step (e.g. AAPL · fetch 1m · backfill (7d)). */
  detail?: string | null;
  started_at: string | null;
  finished_at: string | null;
  last_sync: string | null;
  started?: boolean;
  daily?: DailyRunSummary;
}

/** POST /sync/data — status snapshot plus start metadata. */
export type SyncStartResponse = SyncProgress & {
  started?: boolean;
  reason?: string;
  date?: string;
  resumed?: boolean;
};
