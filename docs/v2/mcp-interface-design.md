# MCP Interface Design

## Principle

MCP tools fetch or compute data. They do not produce investment conclusions. The report workflow consumes tool results, normalizes them into provider dataclasses, runs deterministic skills, and then asks the LLM to explain.

MCP servers should keep tool names small and explicit. The client can discover tools with `tools/list` and call them with `tools/call`; each tool uses a JSON Schema input contract.

## Proposed Servers

| Server | Tools | Purpose |
| --- | --- | --- |
| `china-stock-market-mcp` | `get_realtime_quote`, `get_daily_bars`, `get_market_breadth` | 行情 and market temperature inputs |
| `china-capital-flow-mcp` | `get_money_flow`, `get_margin_data`, `get_lhb` | 主力资金, 融资融券, 龙虎榜 |
| `china-announcement-mcp` | `search_announcements`, `get_announcement_text` | 公司公告 and监管问询 |
| `china-memory-mcp` | `save_analysis_event`, `search_memory`, `record_feedback` | Local memory and feedback |

## Core Tool Contracts

The canonical tool schemas live in `app/mcp/tool_schemas.py` and `mcp/china_stock_tools.json`.

## Local Runtime

`app/mcp/stdio.py` implements the initial JSON-RPC stdio server. It supports
`initialize`, `tools/list`, and `tools/call`; its dispatcher lives in
`app/mcp/server.py`. Start it with:

```powershell
python -m app.mcp.stdio
```

`config/mcp.server.example.json` shows a client configuration. In the current
offline MVP, all market tools use `SampleMarketDataProvider` and label results
with `data_status: latest_available`. A production provider must be injected
before the same tools are treated as real-time data.

## Tool Plugins

The runtime uses `app/tools/registry.py`. Every tool is a schema and a handler
registered into `ToolRegistry`; the MCP server only discovers and dispatches
that registry. A new provider capability can therefore be mounted without
editing MCP request routing. Built-in market and memory tools remain the
default registry entries.

### `get_realtime_quote`

Input:

```json
{
  "symbol": "600519.SH"
}
```

Output:

```json
{
  "symbol": "600519.SH",
  "price": 1526.0,
  "change_pct": 0.42,
  "volume": 123456,
  "amount": 1880000000,
  "as_of": "2026-07-10T15:00:00+08:00",
  "source": "eastmoney"
}
```

### `get_market_breadth`

Input:

```json
{
  "trade_date": "2026-07-10"
}
```

Output includes advancers, decliners, limit-up count, limit-down count, failed-breakout rate, consecutive-board height, and total amount.

### `save_analysis_event`

Input is the normalized report plus user query metadata. It returns a local event id. This tool must be append-only.

## Security and Safety

- Read-only market tools can be pre-approved.
- Memory write tools are local-only and append-only.
- MCP-supplied reports are stored as data only; they are never interpreted as
  instructions or directly executed.
- Any future trading or order tool must require explicit confirmation and is out of v2 scope.
