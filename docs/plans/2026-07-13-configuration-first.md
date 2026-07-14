# Configuration-First Runtime Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove business rules and runtime integration choices from Python source so the TradingOS is configured, versioned, and auditable rather than hard-coded.

**Architecture:** Introduce one typed, validated runtime settings loader with a checked-in default JSON document. Providers, model registry, server defaults, and core scoring thresholds read from it. Immutable protocol names, schema fields, and safety ceilings remain source-code contracts; every mutable market rule is addressed by a named configuration key and the loaded rule version is captured in reports.

**Tech Stack:** Python 3.10 dataclasses, JSON configuration, unittest.

---

### Task 1: Create validated runtime settings

**Files:**
- Create: `config/tradingos.default.json`
- Create: `app/config/runtime.py`
- Test: `tests/test_runtime_config.py`

1. Define provider URLs, timeouts, server defaults, model registry, daily-bar minimum, and rule version.
2. Load a user-specified config path or `TRADINGOS_CONFIG_PATH`, then validate required sections and numeric bounds.
3. Use immutable defaults only to locate the checked-in configuration file.

### Task 2: Move core agent thresholds and weights into configuration

**Files:**
- Modify: `app/agents/common.py`
- Modify: `app/agents/market_agent.py`
- Modify: `app/agents/fundamental_agent.py`
- Modify: `app/agents/technical_agent.py`
- Modify: `app/agents/capital_flow_agent.py`
- Modify: `app/agents/announcement_agent.py`
- Modify: `app/skills/data_readiness.py`
- Test: `tests/test_runtime_config.py`

1. Read score bounds, thresholds, weights, penalties, and confidence parameters from named configuration entries.
2. Preserve existing default behavior under the checked-in default configuration.
3. Prove an override changes one deterministic rule without source edits.

### Task 3: Move provider/runtime endpoints and limits into configuration

**Files:**
- Modify: `app/data/providers/eastmoney_provider.py`
- Modify: `app/market/stock_snapshot.py`
- Modify: `app/market/morning_radar.py`
- Modify: `app/llm/providers.py`
- Modify: `app/web/server.py`
- Test: `tests/test_runtime_config.py`

1. Route public URLs, request timeouts, bounded refresh concurrency, and local server defaults through settings.
2. Keep endpoint allow-lists and response parsing as code-side safety contracts.

### Task 4: Make configuration provenance visible

**Files:**
- Modify: `app/schemas/report.py`
- Modify: `app/graph/workflow.py`
- Modify: `app/reporting/render.py`
- Modify: `README.md`

1. Persist `rule_version` and `config_source` in every report and replay record.
2. Document the distinction between configurable business rules and fixed protocol/security contracts.
3. Run the complete suite and static compilation.
