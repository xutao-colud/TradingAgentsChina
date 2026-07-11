# Portable Memory, Tool Plugins, and Web Console Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Preserve every research question as a portable local summary, make tool capabilities pluggable, and provide a runnable local web console.

**Architecture:** Keep all personal data in the existing local JSONL store. Add append-only interaction summaries plus a versioned import/export bundle with ID-based merge. Replace MCP's fixed dispatcher with a registry and expose the existing research workflow through a standard-library HTTP API and static dashboard.

**Tech Stack:** Python 3.10 standard library (`http.server`, JSON, dataclasses), existing deterministic workflow, HTML/CSS/JavaScript.

---

### Task 1: Portable Memory Bundle

**Files:**
- Modify: `app/memory/local_store.py`
- Modify: `app/cli.py`
- Test: `tests/test_memory.py`

1. Add interaction summary events for every research request.
2. Add versioned export/import APIs that merge JSONL records by event ID.
3. Add CLI import/export operations and tests for cross-store portability.

### Task 2: Pluggable Tool Registry

**Files:**
- Create: `app/tools/registry.py`
- Modify: `app/mcp/server.py`
- Test: `tests/test_mcp_server.py`

1. Define a registry with registration, discovery, and dispatch operations.
2. Register built-in market and memory tools into the registry.
3. Verify an extra tool can be registered without changing the MCP server.

### Task 3: Local Web API and Dashboard

**Files:**
- Create: `app/web/server.py`
- Create: `app/web/static/index.html`
- Create: `app/web/static/app.js`
- Create: `app/web/static/styles.css`
- Modify: `pyproject.toml`
- Test: `tests/test_web_server.py`

1. Add local API routes for analysis, feedback, profile, tool discovery, and memory import/export.
2. Build a single-page dashboard for query, report, profile learning, tools, and portable file operations.
3. Run the server and verify API responses locally.

### Task 4: Documentation and Regression

**Files:**
- Modify: `README.md`
- Modify: `docs/v2/memory-system.md`

1. Document transfer and launch commands.
2. Run the full test suite and an HTTP smoke test.
