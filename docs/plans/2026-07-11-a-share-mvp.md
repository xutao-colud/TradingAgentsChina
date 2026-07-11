# A-Share Research Agent MVP Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a runnable MVP for an A-share focused research agent that analyzes one stock and emits JSON/Markdown reports.

**Architecture:** Use a modular Python package with provider interfaces, deterministic analysis helpers, agent modules, a simple workflow orchestrator, and a CLI. The first provider is offline sample data so the MVP works without API keys or network access.

**Tech Stack:** Python 3.10+, standard library dataclasses, argparse, unittest.

---

### Task 1: Project Skeleton and Docs

**Files:**
- Create: `README.md`
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `docs/adr/0001-offline-provider-first.md`
- Create: `docs/plans/2026-07-11-a-share-mvp.md`

**Steps:**
1. Define the MVP boundary as research-only, single-stock, offline-runnable.
2. Document the CLI command and test command.
3. Capture the architecture decision to start with a sample provider and keep real providers behind an interface.

**Test:** Read docs and verify commands are explicit.

### Task 2: Core Schema and Provider

**Files:**
- Create: `app/schemas/report.py`
- Create: `app/data/providers/base.py`
- Create: `app/data/providers/sample_provider.py`

**Steps:**
1. Add dataclasses for prices, fundamentals, money flow, announcements, market context, agent findings, and final reports.
2. Add a provider protocol with methods for each data category.
3. Implement sample data for `600519.SH` and a generic fallback symbol.

**Test:** Instantiate the provider and retrieve a full data bundle.

### Task 3: Deterministic Helpers and A-Share Rules

**Files:**
- Create: `app/indicators/technical.py`
- Create: `app/rules/trading_rules.py`

**Steps:**
1. Add moving-average, return, and volume-ratio helpers.
2. Add symbol normalization, board classification, daily limit lookup, and invalid-condition checks.

**Test:** Verify `600519` normalizes to `600519.SH` and ST/suspend/liquidity checks produce invalid conditions.

### Task 4: Agent Modules

**Files:**
- Create: `app/agents/*.py`

**Steps:**
1. Add market, fundamental, technical, capital-flow, announcement, and theme agents.
2. Add bull and bear researchers that combine prior findings.
3. Add portfolio manager and risk manager to create the final rating and risk review.

**Test:** Run each agent with sample data and verify each output contains a conclusion, score, evidence, risks, confidence, and source IDs.

### Task 5: Workflow, Reporting, CLI

**Files:**
- Create: `app/graph/state.py`
- Create: `app/graph/workflow.py`
- Create: `app/reporting/render.py`
- Create: `app/cli.py`

**Steps:**
1. Build a workflow that collects provider data, runs agents in order, applies risk review, and returns an `AnalysisReport`.
2. Render Markdown from the same report object used for JSON.
3. Add CLI options for symbol, analysis date, and JSON output.

**Test:** Run `python -m app.cli 600519 --date 2026-07-10 --json`.

### Task 6: Verification Tests

**Files:**
- Create: `tests/test_rules.py`
- Create: `tests/test_workflow.py`

**Steps:**
1. Test symbol normalization and board rules.
2. Test the workflow returns expected schema fields and includes risk gating.
3. Test JSON serialization.

**Test:** Run `python -m unittest discover -s tests`.

