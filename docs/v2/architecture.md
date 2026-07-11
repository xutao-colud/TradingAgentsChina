# A股 TradingAgents v2.0 Architecture

## Goal

v2 turns the MVP from a one-shot research report into a personal A-share research system that can use real data tools, DeepSeek reasoning, and local memory.

The key rule is: data tools fetch facts, deterministic skills compute indicators, DeepSeek explains and debates, memory records every interaction and helps the system adapt to the user's style.

## Requirements

### Functional

- Fetch real-time or near-real-time A-share data through provider adapters or MCP tools.
- Keep the current offline `SampleMarketDataProvider` as a fallback.
- Persist each analysis request, raw normalized data snapshot, report, skills output, and user feedback locally.
- Maintain a `TradingProfile` describing risk tolerance, holding period, preferred setups, avoided patterns, and favorite themes.
- Retrieve recent and similar historical analyses before producing a new report.
- Support DeepSeek as the primary paid reasoning model while keeping model access separate from market data access.

### Non-Functional

- Reproducibility: every report must be traceable to a data snapshot and source timestamps.
- Safety: no automatic trading orders in v2.
- Privacy: local memory is written under `data/memory/` by default and ignored by git.
- Extensibility: data providers, LLM clients, memory stores, and MCP tools are replaceable interfaces.

## High-Level Flow

```text
User request
  -> Orchestrator
  -> Memory Context Loader
       reads TradingProfile + similar reports + feedback
  -> Data Tool Layer
       provider adapters or MCP tools fetch行情/财务/公告/资金/市场情绪
  -> Deterministic Skills
       indicators + A股 skills compute structured signals
  -> Agent Committee
       market/fundamental/technical/capital/news/theme/risk agents
  -> DeepSeek Reasoning Layer
       explains conflict, summarizes debate, adapts language to profile
  -> Report Builder
       JSON + Markdown
  -> Memory Writer
       stores request, snapshots, report, feedback hooks
```

## Components

| Component | Responsibility |
| --- | --- |
| `app/data/providers` | Normalized provider interface and direct data adapters. |
| `app/mcp` | MCP tool schemas for external real-time data servers. |
| `app/skills` | Deterministic China-market skill layer. |
| `app/agents` | Agent findings, debate, decision, and risk review. |
| `app/llm` | DeepSeek/OpenAI-compatible client configuration and prompt contracts. |
| `app/memory` | Local profile, report history, feedback, and retrieval context. |
| `database/schema.sql` | Production PostgreSQL + pgvector schema target. |

## Model Boundary

DeepSeek should not be asked to "get current price." It should receive structured data from tools and then reason over it. This follows the same boundary as the MVP: calculations and facts outside the LLM, interpretation inside the LLM.

DeepSeek's official API currently exposes OpenAI/Anthropic-compatible access with `https://api.deepseek.com` and current model names such as `deepseek-v4-pro` and `deepseek-v4-flash`; older `deepseek-chat` and `deepseek-reasoner` names are marked for deprecation on 2026-07-24. See the official DeepSeek docs referenced in the implementation notes.

## MCP Boundary

MCP servers expose tools, resources, and prompts. In v2 we use tools for live data fetching, resources for local memory/report browsing, and prompts for repeatable workflows like daily review and post-trade feedback. Tool definitions use JSON Schema input contracts and are invoked by `tools/call`.

## Storage Strategy

### v2 Local

- JSON profile: `data/memory/trading_profile.json`
- JSONL reports: `data/memory/analysis_events.jsonl`
- JSONL feedback: `data/memory/feedback_events.jsonl`

### v2 Production Target

- PostgreSQL for normalized entities and reports.
- `pgvector` for embedding-based similar-case retrieval.
- Redis later for short-lived intraday cache.

## Failure Modes

| Failure | Impact | Mitigation |
| --- | --- | --- |
| Real-time data source fails | Report could use stale data | Fall back to cached/offline provider and label freshness. |
| DeepSeek API unavailable | No narrative/debate enhancement | Keep deterministic report path available. |
| Memory write fails | Personalization weakens | Continue report generation and surface warning. |
| Bad profile learning | Agent overfits user bias | Store explicit feedback separately and require profile update review. |

