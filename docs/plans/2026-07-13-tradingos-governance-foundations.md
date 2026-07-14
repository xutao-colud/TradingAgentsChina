# TradingOS Governance Foundations Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the project’s evidence, market-first, court, replay, regime analytics, profile, consent, and no-fabricated-win-rate rules executable and testable.

**Architecture:** Extend the deterministic report contract so every Agent conclusion carries explicit invalidation conditions, and reject incomplete evidence chains into an observation-only result. Add a market-regime gate before personal playbook assessment, enrich the committee with recorded cross-examination and a risk challenge, and preserve replay-ready analysis context. Extend consent-gated outcome records with the market regime and immutable agent score snapshot, then calculate descriptive strategy and Agent results by regime.

**Tech Stack:** Python 3.10 dataclasses, deterministic skills, JSONL local memory, unittest.

---

### Task 1: Enforce the evidence contract

**Files:**
- Modify: `app/schemas/report.py`
- Modify: `app/agents/*.py`
- Modify: `app/skills/evidence_chain.py`
- Modify: `app/reporting/render.py`
- Test: `tests/test_evidence_chain.py`

1. Add explicit per-finding invalidation conditions.
2. Require evidence, source references with source time, counter-evidence, risk, and invalidation conditions in the evidence quality gate.
3. Render the new conditions in Markdown and force weak evidence to observation-only output.

### Task 2: Put market regime before personal playbook selection

**Files:**
- Create: `app/skills/market_strategy_gate.py`
- Modify: `app/graph/workflow.py`
- Modify: `app/playbooks/evaluator.py`
- Test: `tests/test_workflow.py`

1. Derive permitted research playbooks from deterministic market temperature and sentiment inputs.
2. Run this gate before profile alignment and active-playbook assessment.
3. Mark a user-selected playbook ineligible when the current market regime excludes it.

### Task 3: Make the committee a recorded court

**Files:**
- Modify: `app/skills/investment_committee.py`
- Modify: `tests/test_investment_committee.py`

1. Replace all “win-rate proxy” language with “evidence-fit score”.
2. Record each route’s strongest support, strongest challenge, cross-examination, and a global risk challenge before the judge summary.
3. Preserve the existing non-order, non-return-promise guardrail.

### Task 4: Make analysis replayable and evolution metrics regime-aware

**Files:**
- Modify: `app/saas/contracts.py`
- Modify: `app/memory/local_store.py`
- Modify: `app/analytics/strategy_performance.py`
- Test: `tests/test_memory.py`
- Test: `tests/test_strategy_performance.py`

1. Save market regime and agent score snapshot with consent-gated outcome records.
2. Add a replay method that joins the immutable report with its feedback/outcomes.
3. Group strategy observations by playbook and market regime.
4. Add per-Agent, per-regime observational reliability summaries; withhold rates below the sample threshold.

### Task 5: Update product documentation and verify

**Files:**
- Modify: `README.md`
- Modify: `docs/v3/tradingos-product-principles.md`
- Modify: `docs/v3/investment-faction-committee.md`
- Modify: `docs/v3/strategy-analytics.md`

1. Document the executable safeguards and observational limits.
2. Run `python -m unittest discover -s tests`.
