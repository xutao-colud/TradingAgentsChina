# Multi-model Runtime Configuration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let users select and configure DeepSeek, GLM, or Qwen for live report explanation without persisting API keys in Memory exports.

**Architecture:** Use a fixed provider registry of official OpenAI-compatible endpoints. Store non-secret provider/model preferences locally, keep UI-entered keys only in process memory, and fall back to provider-specific environment variables after restart. The model can explain supplied deterministic facts and real-time quote context but cannot alter risk scores or create order instructions.

**Tech Stack:** Python 3.10 standard library HTTP client, existing report/LLM layer, local HTTP API, static JavaScript.

---

### Task 1: Secure Provider Runtime

**Files:**
- Create: `app/llm/providers.py`
- Create: `app/llm/runtime.py`
- Modify: `app/llm/deepseek_client.py`
- Test: `tests/test_model_runtime.py`

1. Define fixed DeepSeek, GLM, and Qwen provider presets.
2. Keep API keys only in an in-memory runtime registry or environment variables.
3. Ensure status responses and portable exports never expose keys.

### Task 2: Real-time Context and Web API

**Files:**
- Modify: `app/schemas/report.py`
- Modify: `app/web/server.py`
- Test: `tests/test_web_server.py`

1. Attach a labelled real-time quote context to web analyses when available.
2. Add model status, configure, and clear endpoints.
3. Route explicit model explanation through the selected provider only.

### Task 3: Dashboard Model Panel

**Files:**
- Modify: `app/web/static/index.html`
- Modify: `app/web/static/app.js`
- Modify: `app/web/static/styles.css`

1. Add provider/model/key configuration controls.
2. Mark keys as session-only and never render them after submission.
3. Enable model explanation only when a configured provider is selected.

### Task 4: Security and Documentation

**Files:**
- Modify: `README.md`
- Create: `docs/v2/model-runtime.md`

1. Add secure response headers and no-store handling for API responses.
2. Document environment-variable persistence, rotation, and export exclusions.
3. Run the full test suite without live API keys.
