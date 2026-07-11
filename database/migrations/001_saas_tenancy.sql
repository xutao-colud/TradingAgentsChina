-- SaaS tenancy migration target for PostgreSQL 15+.
-- Apply through a migration runner, after backfilling existing local/imported data
-- into a designated bootstrap tenant. Do not expose the local stdio server publicly.

BEGIN;

CREATE TABLE IF NOT EXISTS tenants (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    plan_code TEXT NOT NULL DEFAULT 'free',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'deleted')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app_users (
    id UUID PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'deleted')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tenant_memberships (
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    user_id UUID NOT NULL REFERENCES app_users(id),
    role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'member', 'analyst', 'viewer')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id)
);

CREATE TABLE IF NOT EXISTS analytics_consents (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    user_id UUID NOT NULL REFERENCES app_users(id),
    scope TEXT NOT NULL CHECK (scope IN ('strategy_outcome_aggregate')),
    granted BOOLEAN NOT NULL,
    policy_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ
);

-- Existing market reference tables remain global. User-owned records become tenant scoped.
ALTER TABLE trading_profiles ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id);
ALTER TABLE trading_profiles ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES app_users(id);
ALTER TABLE trading_profiles ADD COLUMN IF NOT EXISTS active_playbook TEXT;
ALTER TABLE analysis_reports ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id);
ALTER TABLE analysis_reports ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES app_users(id);
ALTER TABLE analysis_reports ADD COLUMN IF NOT EXISTS active_playbook TEXT;
ALTER TABLE feedback_events ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id);
ALTER TABLE feedback_events ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES app_users(id);
ALTER TABLE memory_events ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id);
ALTER TABLE memory_events ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES app_users(id);

CREATE TABLE IF NOT EXISTS strategy_outcomes (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    user_id UUID NOT NULL REFERENCES app_users(id),
    analysis_report_id UUID NOT NULL REFERENCES analysis_reports(id),
    playbook_id TEXT NOT NULL,
    playbook_fit_score INTEGER NOT NULL CHECK (playbook_fit_score BETWEEN 0 AND 100),
    outcome_return_pct NUMERIC(12, 4) NOT NULL,
    outcome_days INTEGER NOT NULL CHECK (outcome_days > 0),
    outcome_source TEXT NOT NULL CHECK (outcome_source IN ('manual', 'broker_import', 'simulated')),
    consent_id UUID REFERENCES analytics_consents(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Sensitive account data is isolated and is never joined into aggregate strategy analytics.
CREATE TABLE IF NOT EXISTS portfolio_accounts (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    user_id UUID NOT NULL REFERENCES app_users(id),
    currency TEXT NOT NULL DEFAULT 'CNY',
    cash_balance NUMERIC(20, 2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS portfolio_positions (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    user_id UUID NOT NULL REFERENCES app_users(id),
    account_id UUID NOT NULL REFERENCES portfolio_accounts(id),
    symbol TEXT NOT NULL REFERENCES stocks(symbol),
    quantity NUMERIC(22, 4) NOT NULL CHECK (quantity >= 0),
    cost_price NUMERIC(18, 4),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (account_id, symbol)
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID REFERENCES tenants(id),
    user_id UUID REFERENCES app_users(id),
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_strategy_outcomes_tenant_playbook
    ON strategy_outcomes (tenant_id, playbook_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_analysis_reports_tenant_user_date
    ON analysis_reports (tenant_id, user_id, analysis_date DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_created
    ON audit_logs (tenant_id, created_at DESC);

-- Every request transaction must execute:
--   SET LOCAL app.tenant_id = '<tenant UUID>';
-- and authorization middleware must verify tenant_memberships before queries.
ALTER TABLE strategy_outcomes ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY strategy_outcomes_tenant_isolation ON strategy_outcomes
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
CREATE POLICY portfolio_accounts_tenant_isolation ON portfolio_accounts
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
CREATE POLICY portfolio_positions_tenant_isolation ON portfolio_positions
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
CREATE POLICY audit_logs_tenant_isolation ON audit_logs
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

COMMIT;
