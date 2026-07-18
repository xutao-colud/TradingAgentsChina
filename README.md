# TradingAgentsChina

A-share focused research-agent MVP inspired by TradingAgents.

This first version is intentionally small: it runs offline with a sample data provider, separates deterministic calculations from agent reasoning, and produces both JSON and Markdown reports for one stock/date.

## What the MVP Does

- Normalizes A-share symbols such as `600519` to `600519.SH`
- Collects daily price, basic fundamentals, announcements, money flow, market context, and themes from a provider interface
- Runs deterministic agents for market cycle, fundamentals, technical trend, capital flow, announcements, themes, bull case, bear case, portfolio committee, and risk review
- Adds A-share domain skills for market temperature, sentiment cycle, money-making effect, theme lifecycle, main-force behavior, announcement impact, evidence-chain quality, risk scanning, and composite scoring
- Compares multiple A-share investment schools through an investment-faction committee and highlights the currently most persuasive research route
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

## Opportunity pool and three-level analysis

The opportunity pipeline avoids running the full research workflow across the
entire market. It first combines local positions, watchlist symbols, explicit
candidates, and verified radar movers, then applies bounded promotion gates:

- **L1**: deterministic lightweight snapshot scan; no LLM and no deep provider fan-out.
- **L2**: full structured agents and skills without the investment committee.
- **L3**: court-style committee only after market status, data readiness,
  evidence-chain quality, and L2 research gates pass.

The opportunity score measures current evidence coverage and playbook/profile
fit. It is not a win rate, return forecast, or trading instruction. Missing
fields reduce coverage and can block promotion; they are never filled with a
neutral fact.

```powershell
# Positions + watchlist + verified radar, through L3 gates
python -m app.cli --opportunity-scan --date 2026-07-14

# Add explicit candidates and stop after the fast deterministic scan
python -m app.cli 600519 --opportunity-scan --opportunity-symbol 000725 --opportunity-level 1 --no-radar

# Read or replay the locally persisted pool
python -m app.cli --list-opportunity-pool
python -m app.cli --replay-opportunity <EVENT_ID>
```

Web endpoints are `GET /api/opportunities`, `POST /api/opportunities/scan`, and
`POST /api/opportunities/replay`. MCP exposes `scan_opportunity_pool`,
`get_opportunity_pool`, and `replay_opportunity_pool`. Local runs are persisted
under the configured Memory directory; the SaaS target schema is in
`database/migrations/002_opportunity_pool_pipeline.sql`.

## MVP Boundary

The test/demo workflow uses `SampleMarketDataProvider` and is explicitly marked `样例数据`. The CLI and local web server now default to `ProductionMarketDataProvider`: authenticated Tushare is the primary source, while AkShare supplements public daily bars, northbound holdings and holder-trade records. If a token, package, entitlement, or aligned source is unavailable, the report is downgraded to `数据不足`; it never falls back to sample data.

Install the optional production adapters with `pip install -r requirements.txt`, set `TUSHARE_TOKEN` in the deployment environment (see [market-data.env.example](C:\Users\WIN10\Documents\TradingAgentsChina\config\market-data.env.example)), then run the CLI normally. Use `--provider sample` only for offline demonstration and regression testing. Tushare permissions vary by interface: 龙虎榜、两融、沪深股通持股、业绩预告/快报、限售解禁和股东增减持 may require the appropriate account entitlement. The system reports an unavailable source instead of asserting a missing field is negative or neutral.

The risk layer also consumes point-in-time goodwill/net-assets, Tushare equity-pledge statistics, important-shareholder reductions, CNInfo inquiry letters, and rolling amount/turnover observations. Every check reports its source, observation time, counterpoint, risk, and invalidation condition. Thresholds, lookback windows, deductions, and grade boundaries are runtime configuration; failed or unentitled queries remain `数据不足` and are never converted to zero risk.

### Provider snapshots and quality gates

Production Tushare and AkShare calls are captured before normalization under `data/raw/provider_snapshots/` (override with `TRADINGOS_RAW_SNAPSHOT_DIR`). Each JSON snapshot includes sanitized request parameters, provider/interface, request time, source records, record count, status, and a SHA-256 content hash. Credentials listed in runtime configuration are redacted before persistence.

AkShare's global holder-trade query is disabled by default because it can return more than 100,000 rows and cannot produce a complete replay snapshot within the configured snapshot limit. Tushare's symbol-level holder-trade interface is the production default. Operators may explicitly enable the AkShare bulk query in runtime configuration for controlled data-ingestion jobs; interactive analysis never treats the disabled query as “no reduction”.

Normalized daily bars, 龙虎榜 records, and 融资融券 records pass deterministic field/date/range checks before agents can consume them. Failed records are removed rather than converted to neutral values. `AnalysisReport.data_quality_reports` exposes semantic validation and raw-snapshot integrity results, and blocking failures feed the existing data-readiness gate. Provider capability names, dataset rules, snapshot location, redaction keys, and severity behavior live in `config/tradingos.default.json`.

### A股特色市场结构

生产市场状态会从同一交易日的市场宽度与涨跌停池计算封板率、真实炸板率、一字板数量和连板梯队，并将多日观察写入 `sentiment_history`。封板率与炸板率共用“封死涨停 + 炸板”的可审计分母；一字板必须同时满足配置的首次封板时间与零开板次数；连板梯队由配置定义且必须连续覆盖全部板数。字段缺失、梯队无法闭合或比例不一致时，市场状态降级为 `数据不足`。

个股侧增加多日换手率连续变化与价格背离分析。A/H 标的使用 Tushare 官方同日比价记录；接口覆盖期之前、无权限、非 A/H 标的、代码错配、重复记录或比价倍率与溢价不一致时均不参与委员会计分。以上信号只作为可质证的市场情绪、资金参与度或相对估值证据，不产生自动交易指令。

## Configuration first

Mutable runtime settings and investment-rule thresholds live in `config/tradingos.default.json`; set `TRADINGOS_CONFIG_PATH` to point at a validated JSON override. Every report stores the applied rule version and configuration source. Protocol field names, schema contracts, and safety validation remain code-side invariants.

The system is research-only. It should not be used as financial advice or automated trading infrastructure.

## Product Guardrails

Codex and contributors should follow the project-level rules in [AGENTS.md](AGENTS.md): evidence first, memory first, user profile first, strategy first, and evolution first. The product direction is summarized in [A股 TradingOS 产品原则](docs/v3/tradingos-product-principles.md).

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
python -m app.web.server --host 0.0.0.0 --port 8000
```

On this computer, open `http://127.0.0.1:8000`. Devices on the same trusted Wi-Fi/LAN can use `http://<this-computer's-IPv4>:8000`; run `ipconfig` on Windows to find the IPv4 address. The dashboard listens on all local network interfaces. Model-key entry is accepted only when the TCP client address is loopback or an address assigned to the server machine itself; other LAN devices cannot submit or clear keys. Configure keys from the server computer, or set the provider environment variable before startup. Keep the firewall rule on the **Private** profile only and do not expose or port-forward this service to the public internet.

The server defaults to `ProductionMarketDataProvider`, uses authenticated Tushare plus the configured public supplements, and returns `数据不足` when a production dimension is unavailable. It never substitutes `SampleMarketDataProvider` unless the operator explicitly starts it with `--provider sample`.

### Watchlist, account snapshot, and real-time quotes

The web console also includes a local-only intraday board:

- Add/remove a watchlist symbol and an observation note.
- Save available cash, position quantity, and cost price locally.
- Click **刷新实时行情** to query the fixed public quote source and calculate current market value, unrealized P/L, daily P/L, sector tags, and order-size money flow.
- Read the displayed research prompt as a risk/verification reminder, not an order instruction.

Watchlist and portfolio data are included in `trading-agents-memory.json` exports. This file may contain sensitive account information, so store and transfer it securely. The quote response displays its source, date/time, and availability status; it can be unavailable or reflect the latest close outside market hours.

### Morning money radar

The dashboard includes a short-line `早盘资金雷达` panel. It uses a strict source chain: Eastmoney real-time market-wide radar first; then authenticated Tushare `moneyflow_ind_ths` as a **post-market, latest-available** industry-flow fallback; then Sina quotes scoped only to watchlist/positions/opportunity-pool symbols. The latter two must never be described as market-wide intraday money flow. If no source is verifiable it returns `unavailable` and no sample movers. Every response is labelled with `source`, `data_status`, and `as_of`; read [the radar guide](docs/v3/morning-money-radar.md) before using it in a short-line playbook.

## Switchable A-share playbooks

The project includes four public, explainable style archetypes: `hot_money_leader`, `trend_core`, `institutional_growth`, and `institutional_value_dividend`. They are research hypotheses inspired by observable A-share practice, not copies of any named trader or institution.

```powershell
python -m app.cli --list-playbooks
python -m app.cli --playbook trend_core
python -m app.cli 600519 --date 2026-07-10
```

The selected playbook is portable with your Memory bundle. Each report gives a fit result, hard disqualifiers, and an optimization note; a playbook cannot override risk gates. Read the full rules and required backtest gate in [the playbook library](docs/v2/playbook-library.md).

Each report first runs a deterministic market-state gate, then evaluates only market-eligible playbooks against the user’s `TradingProfile`. The `投资流派委员会` records evidence, cross-examination, risk challenge, and judge summary for aggressive hot-money, trend-capacity, institutional growth, value/dividend, policy-cycle, reversal, and defensive routes. Its score is an evidence-fit score for research routing—not a win-rate claim, future-return forecast, or order instruction. See [the committee design](docs/v3/investment-faction-committee.md).

## SaaS evolution reserve

## Intraday, special instruments, and playbook backtests

The production provider now exposes timestamped AkShare minute bars and order-book observations. `盘中分时盘口分析` calculates VWAP, opening/closing volume concentration, recent-volume change, and five-level order-book imbalance. Missing or historical live snapshots stay `unavailable`; order-book imbalance is never presented as proof of a hidden trader's intent.

New/secondary-new stock classification uses the real `list_date`. Convertible-bond research uses Tushare `cb_basic`, `cb_daily`, and the dated underlying-stock close to calculate parity and premium, retaining source ids and official units. These Tushare endpoints require the corresponding account points/permissions.

The backtest engine in `app/backtest/engine.py` enforces close-to-next-open signal timing, T+1 exits, daily-limit/liquidity rejection, commission, stamp duty, and slippage. `trend_core` can use price history directly. `hot_money_leader`, `institutional_growth`, and `institutional_value_dividend` use `PointInTimeDataset`, which hides reports, consensus changes, dividends, and theme memberships until their recorded availability date. Price-only attempts for these three playbooks remain rejected.

```python
from app.backtest.engine import run_backtest
from app.backtest.playbook_specs import build_playbook_spec, build_price_playbook_spec

result = run_backtest(profile, daily_bars, build_price_playbook_spec("trend_core"), regimes=regime_by_date, stress=True)

# Point-in-time records must come from a survivorship-aware historical data pipeline.
spec = build_playbook_spec("institutional_growth", point_in_time_dataset)
growth_result = run_backtest(profile, daily_bars, spec, regimes=regime_by_date, stress=True)
```

Small samples do not display an empirical positive-trade rate. Backtest output is research evidence, not a return promise or automatic order.

The current product remains local single-user software, but the codebase now reserves a multi-tenant SaaS boundary: `TenantContext`, consent-gated strategy outcomes, cautious cohort analytics, and a PostgreSQL RLS migration. Account balances and position details are explicitly excluded from cross-user analytics. Read [the SaaS architecture](docs/v3/saas-architecture.md) and [strategy analytics limits](docs/v3/strategy-analytics.md) before exposing the product to external users.

## Run the local MCP server

```powershell
python -m app.mcp.stdio
```

The MCP runtime defaults to `ProductionMarketDataProvider`. It uses only configured production sources, returns explicit unavailable/data-insufficient states when a source cannot be verified, and never substitutes offline sample records. The sample provider is available only through explicit test/demo construction.

## Optional DeepSeek explanation

Set `DEEPSEEK_API_KEY` in your shell (see `config/deepseek.env.example`), then explicitly enable the explanation layer:

```powershell
$env:DEEPSEEK_API_KEY = "your-key"
python -m app.cli 600519 --date 2026-07-10 --deepseek-explain
```

DeepSeek receives the deterministic report and a compact local-memory summary only to explain evidence, counterexamples, and your strategy fit. It now uses a reverse-audit prompt contract: the model must challenge the current conclusion, list invalidation conditions, and produce strengthen/wait/fail scenarios before giving a narrative. It cannot alter the scores, risk gates, or generate automated orders.

## Multi-model live explanation

The dashboard supports DeepSeek, GLM（智谱）and Qwen（百炼）through fixed official OpenAI-compatible endpoints. Select a provider, model name, and API Key in the **实时解释引擎** card, click **配置当前模型**, then tick **使用当前配置模型解释报告与实时行情上下文** before analysis. Each analysis is bound to that saved provider/model pair; an unsaved selection is rejected instead of falling back to the previous model.

For safety, keys entered in the page are session-only: they are not returned by APIs, never enter Memory exports, and disappear when the local service restarts. Use `DEEPSEEK_API_KEY`, `ZAI_API_KEY`, or `DASHSCOPE_API_KEY` environment variables if you need the key available after a restart. See [the model runtime guide](docs/v2/model-runtime.md) for the exact endpoints and lifecycle, and [the flexibility audit](docs/v3/flexibility-audit.md) for hard-coded areas that should become versioned configuration.
