-- Dashboard tables (run via db/bootstrap.py at startup)

CREATE TABLE IF NOT EXISTS watchlist (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL UNIQUE,
    notes TEXT,
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS holdings_snapshot (
    id SERIAL PRIMARY KEY,
    account_id VARCHAR(64) NOT NULL DEFAULT 'default',
    ticker VARCHAR(32) NOT NULL,
    quantity DOUBLE PRECISION NOT NULL DEFAULT 0,
    avg_cost DOUBLE PRECISION,
    market_price DOUBLE PRECISION,
    market_value DOUBLE PRECISION,
    unrealized_pnl DOUBLE PRECISION,
    currency VARCHAR(8) DEFAULT 'USD',
    snapshot_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    conid VARCHAR(32),
    asset_class VARCHAR(32),
    description TEXT,
    exchange VARCHAR(64),
    side VARCHAR(16),
    multiplier DOUBLE PRECISION,
    report_date VARCHAR(32),
    ibkr_mark_price DOUBLE PRECISION,
    ibkr_position_value DOUBLE PRECISION,
    cost_basis_money DOUBLE PRECISION,
    cost_basis_price DOUBLE PRECISION,
    ibkr_unrealized_pnl DOUBLE PRECISION,
    percent_of_nav DOUBLE PRECISION,
    fx_rate_to_base DOUBLE PRECISION,
    raw_symbol VARCHAR(64),
    source VARCHAR(32) DEFAULT 'manual',
    source_data JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_holdings_snapshot_at ON holdings_snapshot (snapshot_at DESC);
CREATE INDEX IF NOT EXISTS idx_holdings_ticker ON holdings_snapshot (ticker);

CREATE TABLE IF NOT EXISTS stock_ratings (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    rating VARCHAR(16) CHECK (rating IS NULL OR rating IN (
        'STRONG_SELL', 'SELL', 'REDUCE', 'HOLD', 'ACCUMULATE', 'BUY', 'STRONG_BUY'
    )),
    score INTEGER CHECK (score IS NULL OR (score >= -100 AND score <= 100)),
    reasoning TEXT NOT NULL,
    key_drivers JSONB DEFAULT '[]'::jsonb,
    supporting_headlines JSONB DEFAULT '[]'::jsonb,
    price_summary JSONB DEFAULT '{}'::jsonb,
    model VARCHAR(128),
    report_type VARCHAR(16) CHECK (report_type IS NULL OR report_type IN ('core', 'deep')),
    decision_ok BOOLEAN NOT NULL DEFAULT TRUE,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stock_ratings_ticker ON stock_ratings (ticker, created_at DESC);

CREATE TABLE IF NOT EXISTS app_settings (
    key VARCHAR(64) PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS stock_reports (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    report_type VARCHAR(16) NOT NULL CHECK (report_type IN ('core', 'deep')),
    sections JSONB NOT NULL DEFAULT '{}'::jsonb,
    rating JSONB,
    factor_scores JSONB,
    entry_levels JSONB,
    live_price DOUBLE PRECISION,
    model VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stock_reports_ticker_type
    ON stock_reports (ticker, report_type, created_at DESC);

CREATE TABLE IF NOT EXISTS desk_jobs (
    id UUID PRIMARY KEY,
    job_type VARCHAR(32) NOT NULL CHECK (job_type IN (
        'core_analysis', 'deep_dive', 'rescore'
    )),
    ticker VARCHAR(10) NOT NULL,
    status VARCHAR(16) NOT NULL CHECK (status IN (
        'queued', 'running', 'done', 'failed', 'cancelled', 'interrupted'
    )),
    cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
    progress JSONB NOT NULL DEFAULT '{}'::jsonb,
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    worker_id TEXT,
    lease_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_desk_jobs_status_created
    ON desk_jobs (status, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_desk_jobs_ticker_type_status
    ON desk_jobs (ticker, job_type, status);
CREATE INDEX IF NOT EXISTS idx_desk_jobs_status_lease
    ON desk_jobs (status, lease_until);

CREATE TABLE IF NOT EXISTS llm_usage (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    role VARCHAR(16) NOT NULL CHECK (role IN ('analysis', 'research', 'other')),
    model VARCHAR(128) NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd NUMERIC(12, 6) NOT NULL DEFAULT 0,
    meta JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_llm_usage_created_at ON llm_usage (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_usage_role_day ON llm_usage (role, created_at);

CREATE TABLE IF NOT EXISTS watchlist_suggestions (
    ticker VARCHAR(10) PRIMARY KEY,
    reason TEXT NOT NULL,
    suggested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    source VARCHAR(16),
    company_name TEXT,
    company_blurb TEXT,
    sector TEXT,
    industry TEXT,
    brief JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_watchlist_suggestions_expires
    ON watchlist_suggestions (expires_at);
CREATE INDEX IF NOT EXISTS idx_watchlist_suggestions_suggested
    ON watchlist_suggestions (suggested_at DESC);
