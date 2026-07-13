# Domain Knowledge Enhancement Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make theme, technical, fundamental and sentiment analysis A-share-aware, deterministic, configurable and traceable.

**Architecture:** Theme resolution consumes provider concepts and configuration aliases rather than source-code mappings. Technical and financial calculators produce typed snapshots; Agents only interpret their results. Sentiment uses a dated history to calculate breadth, acceleration and deceleration, and emits insufficient evidence without a history window.

**Tech Stack:** Python standard library, existing provider abstractions, versioned JSON configuration, unittest.

---

### Task 1: Add typed context for concepts, statements, peer benchmarks and sentiment history

**Files:**
- Modify: `app/schemas/report.py`
- Modify: `app/data/providers/base.py`
- Modify: `app/data/providers/sample_provider.py`
- Test: `tests/test_domain_signal_contracts.py`

**Step 1:** Write failing construction/serialization tests for optional concept tags, three-statement values and dated sentiment observations.

**Step 2:** Add immutable fields with empty/default values so existing providers remain compatible.

**Step 3:** Run the contract test.

### Task 2: Replace code-level industry mappings with a theme resolver

**Files:**
- Create: `app/knowledge/theme_resolver.py`
- Modify: `config/tradingos.default.json`
- Modify: `app/agents/theme_agent.py`
- Modify: `app/skills/theme_lifecycle.py`
- Test: `tests/test_theme_resolver.py`

**Step 1:** Test that a provider concept has priority over configured industry fallback and that unmatched evidence is explicit.

**Step 2:** Implement alias normalization, source labels, and no-match behavior.

**Step 3:** Run resolver and theme-skill tests.

### Task 3: Build deterministic MACD, BOLL, KDJ and cost-distribution proxy indicators

**Files:**
- Modify: `app/indicators/technical.py`
- Modify: `config/tradingos.default.json`
- Modify: `app/agents/technical_agent.py`
- Test: `tests/test_technical_indicators.py`

**Step 1:** Test known price series for indicator availability and stable output.

**Step 2:** Implement EMA/MACD, Bollinger bands, KDJ and volume-weighted cost-zone proxy. Label the latter as a proxy, not broker chip data.

**Step 3:** Run technical tests and workflow regression.

### Task 4: Add DuPont, three-statement and peer-comparison analysis

**Files:**
- Create: `app/indicators/fundamental.py`
- Modify: `app/schemas/report.py`
- Modify: `app/data/providers/tushare_provider.py`
- Modify: `app/agents/fundamental_agent.py`
- Test: `tests/test_fundamental_analysis.py`

**Step 1:** Test DuPont decomposition and explicit missing-peer behavior.

**Step 2:** Map revenue, net income, operating cash flow, assets and equity from Tushare statements without altering a report when source records are absent.

**Step 3:** Run provider and fundamental-agent tests.

### Task 5: Use sentiment-history changes to identify transitions

**Files:**
- Create: `app/skills/sentiment_dynamics.py`
- Modify: `app/skills/sentiment_cycle.py`
- Modify: `config/tradingos.default.json`
- Test: `tests/test_sentiment_dynamics.py`

**Step 1:** Test recovery, acceleration, deceleration, retreat and insufficient-history states.

**Step 2:** Calculate multi-day deltas/velocity against a configurable baseline; retain the old labels only as output stages.

**Step 3:** Run all domain skill tests.

### Task 6: Wire, document and verify

**Files:**
- Modify: `app/graph/workflow.py`
- Modify: `README.md`
- Test: `tests/test_workflow.py`

**Step 1:** Pass all new structured inputs to Agents and reports.

**Step 2:** Document evidence boundaries and replay requirements.

**Step 3:** Run `python -m unittest discover -s tests` and `git diff --check`.
