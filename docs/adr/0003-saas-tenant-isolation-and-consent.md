# ADR 0003: SaaS Tenant Isolation and Consent-gated Strategy Analytics

## Status

Accepted — 2026-07-11

## Context

TradingAgentsChina will evolve from a local personal tool to a multi-user SaaS. User trading profiles, accounts, positions, strategy selections, and outcomes must not cross organization boundaries. Strategy/outcome analytics can be useful only if they include failures, distinguish association from causation, and respect a user's consent.

## Decision

1. Introduce `TenantContext` as a mandatory service-layer boundary for every future SaaS request.
2. Keep account/position data isolated and exclude it from cross-tenant or cross-user aggregation.
3. Store strategy outcomes separately from raw account data and analyze them only when explicit aggregate-analytics consent is active.
4. Apply PostgreSQL row-level security by `tenant_id`, tenant-scoped unique constraints, audit logs, and short-lived authenticated sessions in the SaaS deployment.
5. Publish correlation only after at least 30 eligible observations; label it as observational and require backtesting before calling a strategy validated.

## Consequences

- The current local store remains a single-user adapter and has no login system.
- The planned SaaS API must not expose the current local unauthenticated endpoints publicly.
- Analytics can guide product improvements but cannot rank individual users or reveal peer-level trading information.
