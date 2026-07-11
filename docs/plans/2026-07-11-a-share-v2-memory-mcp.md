# A-Share TradingAgents v2 Memory and MCP Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add the v2 foundation for real-data tools, DeepSeek reasoning configuration, local memory, and future PostgreSQL/pgvector persistence.

**Architecture:** Keep the deterministic MVP report path intact. Add local append-only JSONL memory now, document the production PostgreSQL schema, define MCP tool contracts, and keep DeepSeek as a replaceable LLM configuration layer.

**Tech Stack:** Python 3.10+, standard library dataclasses/json/pathlib, PostgreSQL target schema, MCP JSON Schema contracts.

---

### Task 1: v2 Architecture Docs

**Files:**
- Create: `docs/v2/architecture.md`
- Create: `docs/v2/memory-system.md`
- Create: `docs/v2/mcp-interface-design.md`
- Create: `docs/plans/2026-07-11-a-share-v2-memory-mcp.md`

**Test:** Docs explain model/data/memory boundaries and v2 failure modes.

### Task 2: Database Schema

**Files:**
- Create: `database/schema.sql`

**Test:** Schema includes stocks, prices, market snapshots, fundamentals, money flow, announcements, trading profiles, reports, feedback events, and memory events.

### Task 3: Local Memory Store

**Files:**
- Create: `app/memory/models.py`
- Create: `app/memory/local_store.py`
- Modify: `app/cli.py`
- Modify: `.gitignore`

**Test:** CLI saves an analysis event by default and can disable saving with `--no-save-memory`.

### Task 4: MCP Tool Contracts

**Files:**
- Create: `app/mcp/tool_schemas.py`
- Create: `mcp/china_stock_tools.json`

**Test:** Tool schema list contains real-time quote, daily bars, market breadth, money flow, announcement search, analysis memory save, and feedback recording.

### Task 5: DeepSeek Config

**Files:**
- Create: `app/llm/config.py`
- Create: `config/deepseek.env.example`

**Test:** Config loads defaults without an API key and reports unconfigured state.

### Task 6: Verification

**Files:**
- Create: `tests/test_memory.py`
- Create: `tests/test_mcp_contracts.py`
- Modify: `tests/test_workflow.py` if needed

**Test:** Run `python -m unittest discover -s tests`.

