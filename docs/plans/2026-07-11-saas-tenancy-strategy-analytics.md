# SaaS Tenancy and Strategy Analytics Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reserve multi-tenant SaaS boundaries and add consent-gated, statistically cautious strategy/outcome analysis contracts.

**Architecture:** Keep the local JSONL product as a single-user adapter. Add pure domain contracts and analytics that can be reused by PostgreSQL repositories later, a tenant-scoped production migration, and architecture/ADR documentation. Account balances and position-level data are never analytics inputs.

**Tech Stack:** Python 3.10 dataclasses/statistics, PostgreSQL 15+ migration target, existing local Memory events.

---

### Task 1: Tenancy Contracts and Strategy Analytics

**Files:**
- Create: `app/saas/contracts.py`
- Create: `app/analytics/strategy_performance.py`
- Test: `tests/test_strategy_performance.py`

1. Define tenant, consent, and immutable outcome contracts.
2. Aggregate only consented outcome records and classify samples below 30 as exploratory.
3. Compute descriptive return metrics and a Pearson association without claiming causality.

### Task 2: Local Outcome Adapter

**Files:**
- Modify: `app/memory/local_store.py`
- Test: `tests/test_memory.py`

1. Convert local outcome feedback linked to reports into strategy outcome records.
2. Preserve active playbook and fit score for later evaluation.
3. Do not derive outcomes from portfolio balances or positions.

### Task 3: Production Schema and Architecture

**Files:**
- Create: `database/migrations/001_saas_tenancy.sql`
- Create: `docs/v3/saas-architecture.md`
- Create: `docs/adr/0003-saas-tenant-isolation-and-consent.md`

1. Add tenants, users, memberships, consent, strategy outcomes, audit logs, and RLS policies.
2. Document deployment, security, failure, and scaling boundaries.

### Task 4: Documentation and Verification

**Files:**
- Modify: `README.md`
- Create: `docs/v3/strategy-analytics.md`

1. Document what can and cannot be inferred from outcome correlation.
2. Run the full test suite.
