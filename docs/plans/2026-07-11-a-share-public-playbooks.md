# A-share Public Playbooks Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add switchable, portable A-share public-style playbooks with deterministic fit assessments and practical optimization prompts.

**Architecture:** Keep playbooks as a versioned catalog of public archetypes, not named-person replication. Persist the user's active selection inside `TradingProfile`; evaluate it after deterministic domain Skills and expose it through CLI, MCP-compatible local API, and the dashboard.

**Tech Stack:** Python 3.10 dataclasses, existing Skill pipeline, stdlib HTTP API, static JavaScript dashboard.

---

### Task 1: Playbook Catalog and Decision Record

**Files:**
- Create: `app/playbooks/catalog.py`
- Create: `app/playbooks/evaluator.py`
- Create: `docs/adr/0002-public-playbook-archetypes.md`
- Test: `tests/test_playbooks.py`

1. Define four public archetypes: hot-money leader, trend core, institutional growth, and institutional value/dividend.
2. Give every archetype explicit regime filters, invalidating conditions, and optimization guidance.
3. Test deterministic fit and incompatible-market downgrades.

### Task 2: Persisted Switching and Workflow Integration

**Files:**
- Modify: `app/memory/models.py`
- Modify: `app/memory/local_store.py`
- Modify: `app/graph/workflow.py`
- Modify: `app/agents/portfolio_manager.py`
- Test: `tests/test_memory.py`, `tests/test_workflow.py`

1. Store the active playbook in portable `TradingProfile` bundles.
2. Add a playbook assessment Skill to each report.
3. Prevent an incompatible active playbook from upgrading the final conclusion.

### Task 3: CLI and Dashboard Switcher

**Files:**
- Modify: `app/cli.py`
- Modify: `app/web/server.py`
- Modify: `app/web/static/index.html`
- Modify: `app/web/static/app.js`
- Modify: `app/web/static/styles.css`
- Test: `tests/test_web_server.py`

1. Add CLI discovery and activation operations.
2. Add local API discovery and activation routes.
3. Add a dashboard selector with fit, filters, and optimization output.

### Task 4: Documentation and Verification

**Files:**
- Create: `docs/v2/playbook-library.md`
- Modify: `README.md`

1. Document limitations and a required backtest gate before promoting a style.
2. Run all tests and a local HTTP smoke test.
