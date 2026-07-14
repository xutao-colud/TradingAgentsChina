# Data Integrity and Reasoning Audit Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent incomplete, stale, sample, or mixed market data from producing strong A-share research conclusions, while making the deterministic reasoning path clearer and more stable.

**Architecture:** Add a data-readiness gate that evaluates source availability, provenance, and time alignment before rating a report. Propagate that gate to Agent confidence and final report conclusions. Keep price history strict: a realtime snapshot is never substituted for historical bars. Separate risk severity from universal research caveats and ensure composite scoring uses only investable-signal categories.

**Tech Stack:** Python 3.10 dataclasses, deterministic provider interfaces and skills, unittest.

---

### Task 1: Make market-data fallback truthful

**Files:**
- Modify: `app/data/providers/eastmoney_provider.py`
- Test: `tests/test_eastmoney_provider.py`

1. Reject realtime snapshot substitution when historical K-line retrieval fails.
2. Reject a snapshot whose source trade date does not equal the requested date.
3. Preserve the unavailable source status for the evidence gate instead of inventing a price series.

### Task 2: Add deterministic data-readiness gate

**Files:**
- Create: `app/skills/data_readiness.py`
- Modify: `app/graph/workflow.py`
- Modify: `app/schemas/report.py`
- Modify: `app/agents/portfolio_manager.py`
- Modify: `app/reporting/render.py`
- Test: `tests/test_data_readiness.py`
- Test: `tests/test_workflow.py`

1. Audit required source IDs, source status/type, and trade-date alignment.
2. Mark sample-only, mixed, unavailable, or stale inputs explicitly.
3. Cap conclusion/confidence to observation or insufficient-evidence levels when readiness is weak.

### Task 3: Repair reasoning aggregation and risk semantics

**Files:**
- Modify: `app/skills/stock_score_model.py`
- Modify: `app/agents/risk_manager.py`
- Test: `tests/test_reasoning_guards.py`

1. Exclude evidence-quality, route-selection, personalization, and committee outputs from investable composite score calculation.
2. Derive the risk level from actual rule/risk triggers and risk-scan grade, not the count of generic caveats.
3. Assert that healthy fully sourced data does not become high-risk solely because every Agent disclosed a caution.

### Task 4: Verify end-to-end behavior

**Files:**
- Modify: `README.md`
- Test: `tests/test_workflow.py`

1. Document the sample/mixed-data report boundary.
2. Run `python -m unittest discover -s tests`, `python -m compileall -q app`, and a CLI smoke test.
