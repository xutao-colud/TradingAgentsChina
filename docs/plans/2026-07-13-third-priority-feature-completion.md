# Third Priority Feature Completion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add traceable intraday analysis, A-share special-instrument rules, a bias-aware playbook backtest engine, and tiered money-flow interpretation.

**Architecture:** Typed provider data enters deterministic analyzers. The research workflow consumes only timestamped results and exposes explicit insufficiency when data is absent. Backtests execute next-bar with configurable friction and produce regime-level descriptive metrics.

**Tech Stack:** Python dataclasses, existing `MarketDataProvider`, AkShare/Tushare adapters, `unittest`, JSON runtime configuration.

---

### Task 1: Data contracts and configuration

Create typed intraday bars, order-book levels, instrument metadata and money-flow tiers. Put provider names, thresholds and execution costs in `config/tradingos.default.json`; validate required sections.

### Task 2: Intraday analysis

Add an AkShare adapter for minute bars and bid/ask snapshots. Compute VWAP, period-volume distribution, opening/closing concentration, order-book imbalance and evidence quality without asking an LLM to inspect a chart.

### Task 3: Special instruments

Classify IPO stage from listing date and evaluate configurable trading constraints. Add convertible-bond premium, parity and liquidity observations with explicit missing-data behavior.

### Task 4: Backtest engine

Run zero-discretion long-only rule functions with next-bar execution, T+1 exits, limit/liquidity rejections and configurable friction. Report drawdown, expectancy, win/loss ratio, sample sufficiency and performance by supplied market regime.

### Task 5: Tiered money flow

Preserve super-large, large, medium and small net flows. Describe divergence and concentration as observed behavior; never assert manipulation or certain institutional intent.

### Task 6: Verification

Add unit tests for timestamps, unavailable data, special-instrument boundaries, look-ahead protection, T+1, friction and tiered-flow divergence. Run the entire suite, compile the package and check the diff.
