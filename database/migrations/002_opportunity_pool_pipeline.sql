-- Tenant-scoped persistence for the market-first opportunity pool.
-- Scores are observational evidence/fit scores, never promised win rates.

BEGIN;

CREATE TABLE IF NOT EXISTS opportunity_pool_runs (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    user_id UUID NOT NULL REFERENCES app_users(id),
    analysis_date DATE NOT NULL,
    market_regime TEXT NOT NULL,
    market_data_status TEXT NOT NULL,
    pipeline_status TEXT NOT NULL CHECK (pipeline_status IN ('completed', 'partial', 'empty')),
    level_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    rule_version TEXT NOT NULL,
    config_source TEXT NOT NULL,
    pool_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS opportunity_candidates (
    pool_run_id UUID NOT NULL REFERENCES opportunity_pool_runs(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    stage TEXT NOT NULL,
    data_status TEXT NOT NULL,
    source_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    level1_score INTEGER NOT NULL CHECK (level1_score BETWEEN 0 AND 100),
    data_coverage NUMERIC(7, 6) NOT NULL CHECK (data_coverage BETWEEN 0 AND 1),
    research_score INTEGER CHECK (research_score BETWEEN 0 AND 100),
    data_readiness_score INTEGER CHECK (data_readiness_score BETWEEN 0 AND 100),
    evidence_chain_score INTEGER CHECK (evidence_chain_score BETWEEN 0 AND 100),
    profile_fit_score INTEGER CHECK (profile_fit_score BETWEEN 0 AND 100),
    promotion_score INTEGER CHECK (promotion_score BETWEEN 0 AND 100),
    highest_completed_level INTEGER NOT NULL CHECK (highest_completed_level BETWEEN 1 AND 3),
    level2_analysis_event_id UUID,
    level3_analysis_event_id UUID,
    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    counterpoints JSONB NOT NULL DEFAULT '[]'::jsonb,
    risks JSONB NOT NULL DEFAULT '[]'::jsonb,
    invalidation_conditions JSONB NOT NULL DEFAULT '[]'::jsonb,
    error TEXT,
    PRIMARY KEY (pool_run_id, symbol)
);

ALTER TABLE analysis_reports ADD COLUMN IF NOT EXISTS analysis_level INTEGER
    CHECK (analysis_level BETWEEN 2 AND 3);
ALTER TABLE analysis_reports ADD COLUMN IF NOT EXISTS opportunity_pool_run_id UUID
    REFERENCES opportunity_pool_runs(id);

CREATE INDEX IF NOT EXISTS idx_opportunity_pool_tenant_date
    ON opportunity_pool_runs (tenant_id, user_id, analysis_date DESC, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_opportunity_candidates_rank
    ON opportunity_candidates (pool_run_id, highest_completed_level DESC, promotion_score DESC, level1_score DESC);

ALTER TABLE opportunity_pool_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE opportunity_candidates ENABLE ROW LEVEL SECURITY;

CREATE POLICY opportunity_pool_runs_tenant_isolation ON opportunity_pool_runs
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
CREATE POLICY opportunity_candidates_tenant_isolation ON opportunity_candidates
    USING (
        EXISTS (
            SELECT 1
            FROM opportunity_pool_runs run
            WHERE run.id = opportunity_candidates.pool_run_id
              AND run.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM opportunity_pool_runs run
            WHERE run.id = opportunity_candidates.pool_run_id
              AND run.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
    );

COMMIT;
