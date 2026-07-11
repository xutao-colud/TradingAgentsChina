# Watchlist, Portfolio Snapshot, and Real-time Quote Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add portable watchlist and account snapshots, current-day gain/loss and research guidance, plus click-to-refresh real-time A-share quotes.

**Architecture:** Store watchlist and manually entered account/positions locally beside Memory and include them in the portable bundle. Query only a fixed quote endpoint through a strict symbol mapper and typed parser. The web API computes portfolio snapshots and deterministic research prompts; it never places orders.

**Tech Stack:** Python 3.10 standard library (`urllib`, JSON), local web server, static JavaScript/CSS.

---

### Task 1: Secure Real-time Quote Adapter

**Files:**
- Create: `app/market/realtime.py`
- Test: `tests/test_realtime_quotes.py`

1. Map normalized A-share symbols to fixed Sina quote identifiers.
2. Parse only known quote fields into typed data.
3. Return a labelled unavailable result on network/provider failure.

### Task 2: Portable Watchlist and Portfolio Snapshot

**Files:**
- Modify: `app/memory/local_store.py`
- Create: `app/portfolio/snapshot.py`
- Test: `tests/test_portfolio_snapshot.py`, `tests/test_memory.py`

1. Persist watchlist, cash balance, and positions locally.
2. Include these values in portable import/export bundles.
3. Compute cost, market value, total P/L, daily P/L, and conservative research prompts.

### Task 3: Local API and Dashboard

**Files:**
- Modify: `app/web/server.py`
- Modify: `app/web/static/index.html`
- Modify: `app/web/static/app.js`
- Modify: `app/web/static/styles.css`
- Test: `tests/test_web_server.py`

1. Add watchlist, quote refresh, account balance, and position endpoints.
2. Render a watchlist and account board with status, day change, and research prompt.
3. Use a click action for real-time refresh; label stale/unavailable responses visibly.

### Task 4: Documentation and Verification

**Files:**
- Modify: `README.md`

1. Document local-only account storage and quote-source limitations.
2. Run unit tests plus local HTTP smoke tests.
