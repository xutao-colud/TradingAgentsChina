# TradingAgentsChina

A-share focused research-agent MVP inspired by TradingAgents.

This first version is intentionally small: it runs offline with a sample data provider, separates deterministic calculations from agent reasoning, and produces both JSON and Markdown reports for one stock/date.

## What the MVP Does

- Normalizes A-share symbols such as `600519` to `600519.SH`
- Collects daily price, basic fundamentals, announcements, money flow, market context, and themes from a provider interface
- Runs deterministic agents for market cycle, fundamentals, technical trend, capital flow, announcements, themes, bull case, bear case, portfolio committee, and risk review
- Adds A-share domain skills for market temperature, sentiment cycle, money-making effect, theme lifecycle, main-force behavior, announcement impact, risk scanning, and composite scoring
- Applies China-specific trading rules such as ST flags, board daily limit ranges, liquidity checks, and suspend checks
- Outputs a traceable research report instead of direct automated trading orders

## Quick Start

```powershell
python -m app.cli 600519 --date 2026-07-10 --json
```

By default, each CLI run saves the analysis to local memory under `data/memory/`.

Disable memory saving:

```powershell
python -m app.cli 600519 --date 2026-07-10 --no-save-memory
```

Markdown report:

```powershell
python -m app.cli 600519 --date 2026-07-10
```

Run tests:

```powershell
python -m unittest discover -s tests
```

## MVP Boundary

The default provider is `SampleMarketDataProvider`, so the pipeline is reliable without network access. Real providers should implement `MarketDataProvider` in `app/data/providers/base.py` and can be swapped into `build_default_workflow()`.

The system is research-only. It should not be used as financial advice or automated trading infrastructure.

## v2 Direction

The v2 foundation adds:

- Local Memory: `app/memory/` writes reports and feedback as append-only JSONL.
- Trading Profile: default style and risk preferences live in `data/memory/trading_profile.json`.
- Database target: `database/schema.sql` defines PostgreSQL + pgvector tables for production.
- MCP contracts: `app/mcp/tool_schemas.py` and `mcp/china_stock_tools.json` define real-time quote, daily bars, market breadth, money flow, announcements, memory save, and feedback tools.
- MCP runtime: `python -m app.mcp.stdio` now exposes those tools through standard input/output. `config/mcp.server.example.json` is a client configuration template.
- DeepSeek config: `app/llm/config.py` reads `DEEPSEEK_*` environment variables, with an example in `config/deepseek.env.example`.

## Personal Trading Profile

Each run loads `data/memory/trading_profile.json` and adds a transparent `个人交易画像适配` Skill to the report. Record an explicit preference or rule locally:

```powershell
python -m app.cli 600519 --feedback "我不喜欢追高，倾向趋势回踩低吸" --feedback-type preference
python -m app.cli 600519 --feedback "退潮期不做高位接力" --feedback-type rule --learned-rule "退潮期不做高位接力"
```

Only explicit preference/rule feedback changes the profile. Outcome feedback is stored for later review and never silently rewrites your style.

### Move your style to another computer

Every completed analysis now writes both the full report and a compact question/answer summary to local memory. Export one portable JSON file:

```powershell
python -m app.cli --export-memory my-a-share-memory.json
```

Copy that file to the new computer, then merge it into the same project:

```powershell
python -m app.cli --import-memory my-a-share-memory.json
```

The import keeps existing local events and merges new reports, feedback, and question summaries by event ID. The Trading Profile in the newest bundle version is restored automatically.

## Local web console

Run the first dashboard version:

```powershell
python -m app.web.server --port 8000
```

Open `http://127.0.0.1:8000`. The page supports analysis, personal-style feedback, portable memory import/export, report rendering, and discovery of mounted MCP tools. It is a local-only app; the initial data source remains `SampleMarketDataProvider`.

### Watchlist, account snapshot, and real-time quotes

The web console also includes a local-only intraday board:

- Add/remove a watchlist symbol and an observation note.
- Save available cash, position quantity, and cost price locally.
- Click **刷新实时行情** to query the fixed public quote source and calculate current market value, unrealized P/L, and daily P/L.
- Read the displayed research prompt as a risk/verification reminder, not an order instruction.

Watchlist and portfolio data are included in `trading-agents-memory.json` exports. This file may contain sensitive account information, so store and transfer it securely. The quote response displays its source, date/time, and availability status; it can be unavailable or reflect the latest close outside market hours.

## Switchable A-share playbooks

The project includes four public, explainable style archetypes: `hot_money_leader`, `trend_core`, `institutional_growth`, and `institutional_value_dividend`. They are research hypotheses inspired by observable A-share practice, not copies of any named trader or institution.

```powershell
python -m app.cli --list-playbooks
python -m app.cli --playbook trend_core
python -m app.cli 600519 --date 2026-07-10
```

The selected playbook is portable with your Memory bundle. Each report gives a fit result, hard disqualifiers, and an optimization note; a playbook cannot override risk gates. Read the full rules and required backtest gate in [the playbook library](docs/v2/playbook-library.md).

## SaaS evolution reserve

The current product remains local single-user software, but the codebase now reserves a multi-tenant SaaS boundary: `TenantContext`, consent-gated strategy outcomes, cautious cohort analytics, and a PostgreSQL RLS migration. Account balances and position details are explicitly excluded from cross-user analytics. Read [the SaaS architecture](docs/v3/saas-architecture.md) and [strategy analytics limits](docs/v3/strategy-analytics.md) before exposing the product to external users.

## Run the local MCP server

```powershell
python -m app.mcp.stdio
```

The current runtime uses the offline sample provider, so its quote tools return `data_status: latest_available` rather than claiming live market data. Swap in an authenticated production provider before relying on it for real-time facts.

## Optional DeepSeek explanation

Set `DEEPSEEK_API_KEY` in your shell (see `config/deepseek.env.example`), then explicitly enable the explanation layer:

```powershell
$env:DEEPSEEK_API_KEY = "your-key"
python -m app.cli 600519 --date 2026-07-10 --deepseek-explain
```

DeepSeek receives the deterministic report and a compact local-memory summary only to explain evidence, counterexamples, and your strategy fit. It cannot alter the scores, risk gates, or generate automated orders.

## Multi-model live explanation

The dashboard supports DeepSeek, GLM（智谱）and Qwen（百炼）through fixed official OpenAI-compatible endpoints. Select a provider, model name, and API Key in the **实时解释引擎** card, then tick **使用当前配置模型解释报告与实时行情上下文** before analysis.

For safety, keys entered in the page are session-only: they are not returned by APIs, never enter Memory exports, and disappear when the local service restarts. Use `DEEPSEEK_API_KEY`, `ZAI_API_KEY`, or `DASHSCOPE_API_KEY` environment variables if you need the key available after a restart. See [the model runtime guide](docs/v2/model-runtime.md) for the exact endpoints and lifecycle.
# TradingAgentsChina
