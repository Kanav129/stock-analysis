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
    ticker VARCHAR(10) NOT NULL,
    quantity DOUBLE PRECISION NOT NULL DEFAULT 0,
    avg_cost DOUBLE PRECISION,
    market_price DOUBLE PRECISION,
    market_value DOUBLE PRECISION,
    unrealized_pnl DOUBLE PRECISION,
    currency VARCHAR(8) DEFAULT 'USD',
    snapshot_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_holdings_snapshot_at ON holdings_snapshot (snapshot_at DESC);
CREATE INDEX IF NOT EXISTS idx_holdings_ticker ON holdings_snapshot (ticker);

CREATE TABLE IF NOT EXISTS stock_ratings (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    rating VARCHAR(16) NOT NULL CHECK (rating IN (
        'STRONG_SELL', 'SELL', 'REDUCE', 'HOLD', 'ACCUMULATE', 'BUY', 'STRONG_BUY'
    )),
    score INTEGER NOT NULL CHECK (score >= -100 AND score <= 100),
    reasoning TEXT NOT NULL,
    key_drivers JSONB DEFAULT '[]'::jsonb,
    supporting_headlines JSONB DEFAULT '[]'::jsonb,
    price_summary JSONB DEFAULT '{}'::jsonb,
    model VARCHAR(128),
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
