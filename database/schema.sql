-- A股 TradingAgents v2 production schema target.
-- PostgreSQL 15+ recommended. Enable pgvector when using semantic retrieval.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS stocks (
    symbol TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    industry TEXT,
    board TEXT NOT NULL,
    is_st BOOLEAN NOT NULL DEFAULT FALSE,
    is_suspended BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS market_snapshots (
    id BIGSERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    source TEXT NOT NULL,
    index_name TEXT NOT NULL,
    index_change_pct NUMERIC(10, 4),
    total_amount NUMERIC(20, 2),
    advancers INTEGER,
    decliners INTEGER,
    limit_up_count INTEGER,
    limit_down_count INTEGER,
    failed_breakout_rate NUMERIC(10, 4),
    yesterday_limit_up_premium NUMERIC(10, 4),
    max_consecutive_boards INTEGER,
    first_board_count INTEGER,
    second_board_success_rate NUMERIC(10, 4),
    strong_stock_return NUMERIC(10, 4),
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (trade_date, source, index_name)
);

CREATE TABLE IF NOT EXISTS daily_prices (
    symbol TEXT NOT NULL REFERENCES stocks(symbol),
    trade_date DATE NOT NULL,
    source TEXT NOT NULL,
    open NUMERIC(18, 4),
    high NUMERIC(18, 4),
    low NUMERIC(18, 4),
    close NUMERIC(18, 4),
    volume NUMERIC(22, 4),
    amount NUMERIC(22, 4),
    turnover_rate NUMERIC(10, 4),
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, trade_date, source)
);

CREATE TABLE IF NOT EXISTS fundamentals (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL REFERENCES stocks(symbol),
    report_date DATE,
    source TEXT NOT NULL,
    revenue_growth_yoy NUMERIC(10, 4),
    profit_growth_yoy NUMERIC(10, 4),
    roe NUMERIC(10, 4),
    gross_margin NUMERIC(10, 4),
    debt_to_asset NUMERIC(10, 4),
    pe_ttm NUMERIC(12, 4),
    pb NUMERIC(12, 4),
    cashflow_quality NUMERIC(10, 4),
    forecast_revision TEXT,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS money_flow_snapshots (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL REFERENCES stocks(symbol),
    trade_date DATE NOT NULL,
    source TEXT NOT NULL,
    main_net_inflow NUMERIC(22, 4),
    super_large_net_inflow NUMERIC(22, 4),
    margin_balance_change NUMERIC(10, 4),
    northbound_signal TEXT,
    turnover_rate NUMERIC(10, 4),
    block_trade_signal TEXT,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol, trade_date, source)
);

CREATE TABLE IF NOT EXISTS announcements (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL REFERENCES stocks(symbol),
    published_at TIMESTAMPTZ,
    priority TEXT NOT NULL,
    sentiment TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    source_id TEXT,
    source TEXT NOT NULL,
    url TEXT,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trading_profiles (
    id BIGSERIAL PRIMARY KEY,
    profile_key TEXT NOT NULL UNIQUE DEFAULT 'default',
    style TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    holding_period TEXT NOT NULL,
    preferred_setups JSONB NOT NULL DEFAULT '[]'::jsonb,
    avoid_patterns JSONB NOT NULL DEFAULT '[]'::jsonb,
    favorite_themes JSONB NOT NULL DEFAULT '[]'::jsonb,
    review_rules JSONB NOT NULL DEFAULT '[]'::jsonb,
    version INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS analysis_reports (
    id UUID PRIMARY KEY,
    symbol TEXT NOT NULL REFERENCES stocks(symbol),
    analysis_date DATE NOT NULL,
    user_query TEXT,
    model_name TEXT,
    conclusion TEXT,
    risk_level TEXT,
    data_status TEXT,
    confidence NUMERIC(10, 4),
    report_json JSONB NOT NULL,
    report_markdown TEXT,
    profile_version INTEGER,
    embedding vector(1536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_analysis_reports_symbol_date
    ON analysis_reports(symbol, analysis_date DESC);

CREATE INDEX IF NOT EXISTS idx_analysis_reports_embedding
    ON analysis_reports USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE TABLE IF NOT EXISTS feedback_events (
    id UUID PRIMARY KEY,
    analysis_report_id UUID REFERENCES analysis_reports(id),
    symbol TEXT REFERENCES stocks(symbol),
    feedback_type TEXT NOT NULL,
    user_comment TEXT,
    outcome_return_pct NUMERIC(10, 4),
    outcome_days INTEGER,
    learned_rule TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memory_events (
    id UUID PRIMARY KEY,
    event_type TEXT NOT NULL,
    symbol TEXT,
    analysis_date DATE,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
