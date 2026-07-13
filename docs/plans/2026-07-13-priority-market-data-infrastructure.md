# Priority Market Data Infrastructure Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace sample-backed production analysis with traceable AkShare/Tushare data adapters and expose short-term A-share signals for 龙虎榜、两融、北向、业绩与减持解禁风险.

**Architecture:** Extend the provider contract with an optional `AshareMarketSignals` payload, preserving the existing report interface. The Tushare adapter supplies authenticated, timestamped records; AkShare supplies public supplemental records. A production provider composes both but emits `unavailable` evidence rather than silently using `SampleMarketDataProvider`. Deterministic agents interpret only structured records.

**Tech Stack:** Python standard library, optional `akshare` and `tushare` packages, environment-variable token configuration, unittest with injected table clients.

---

### Task 1: Introduce typed extended-market-data contracts

**Files:**
- Modify: `app/schemas/report.py`
- Modify: `app/data/providers/base.py`
- Test: `tests/test_market_data_contracts.py`

**Step 1:** Write tests that construct 龙虎榜、两融、北向与公司事件 records and verify their source/time fields survive serialization.

**Step 2:** Add immutable signal dataclasses and a non-abstract `get_market_signals()` provider method returning an explicit unavailable payload.

**Step 3:** Run `python -m unittest discover -s tests -p "test_market_data_contracts.py"`.

### Task 2: Add configurable, injectable AkShare and Tushare adapters

**Files:**
- Create: `app/data/providers/tushare_provider.py`
- Create: `app/data/providers/akshare_provider.py`
- Modify: `config/tradingos.default.json`
- Modify: `app/config/runtime.py`
- Modify: `requirements.txt`
- Test: `tests/test_tushare_provider.py`
- Test: `tests/test_akshare_provider.py`

**Step 1:** Write mocked-client tests for code conversion, tables, fallback ordering, and evidence timestamps.

**Step 2:** Implement lazy optional imports and dependency injection. Read `TUSHARE_TOKEN` only from environment; never write a token to config, logs, or evidence.

**Step 3:** Map Tushare interfaces `top_list`/`top_inst`, `margin_detail`, `hk_hold`, `forecast`, `express`, `share_float`, and `stk_holdertrade` to typed signals. Map AkShare public interfaces as supplemental calls where present.

**Step 4:** Run adapter test files with no network calls.

### Task 3: Compose a production provider and enforce source truthfulness

**Files:**
- Create: `app/data/providers/production_provider.py`
- Modify: `app/graph/workflow.py`
- Modify: `app/cli.py`
- Modify: `app/web/server.py`
- Test: `tests/test_production_provider.py`

**Step 1:** Write failing test showing unavailable production data cannot be relabelled as sample/verified.

**Step 2:** Compose authenticated Tushare with AkShare supplemental data; preserve per-domain provenance and timestamps.

**Step 3:** Add a `--provider` selection that uses production only when configured; keep offline sample mode explicit for tests/demo.

**Step 4:** Run workflow tests.

### Task 4: Add deterministic 龙虎榜 and event-risk analysis

**Files:**
- Create: `app/agents/dragon_tiger_agent.py`
- Modify: `app/agents/capital_flow_agent.py`
- Modify: `app/agents/announcement_agent.py`
- Modify: `app/graph/state.py`
- Modify: `app/graph/workflow.py`
- Modify: `app/skills/data_readiness.py`
- Test: `tests/test_dragon_tiger_agent.py`
- Test: `tests/test_production_workflow.py`

**Step 1:** Write tests for institution/active-seat evidence, margin direction, northbound holding direction, earnings warning, unlock, and reduction events.

**Step 2:** Implement a score-free factual 龙虎榜 Agent that returns evidence, counter-evidence, risks, and invalidation conditions. Extend other agents only with fields received from providers.

**Step 3:** Require source type and as-of date for all time-sensitive new sources; missing data lowers readiness rather than creating a negative/positive signal.

**Step 4:** Run full suite.

### Task 5: Document setup and validate end-to-end behavior

**Files:**
- Modify: `README.md`
- Modify: `config/deepseek.env.example` or create `config/market-data.env.example`
- Test: `tests/test_runtime_config.py`

**Step 1:** Document optional dependency install, `TUSHARE_TOKEN`, provider selection, permission/rate-limit caveats, and evidence status labels.

**Step 2:** Add a configuration test proving tokens stay external and a missing token yields unavailable data.

**Step 3:** Run `python -m unittest discover -s tests` and `git diff --check`.
