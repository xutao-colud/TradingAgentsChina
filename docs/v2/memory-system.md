# Memory System Design

## Purpose

Memory makes the agent increasingly aligned with the user's A-share style. It records facts, preferences, and outcomes separately so the system can learn without mixing market data with opinions.

## Memory Layers

| Layer | Stores | Examples |
| --- | --- | --- |
| Fact Memory | normalized inputs and reports | `600519.SH`, date, market context, skill scores, final conclusion |
| Trading Profile | stable user preferences | low-chase, trend pullback, avoid ST, 1-3 month horizon |
| Experience Memory | feedback and outcomes | "this setup worked", "failed due to退潮期", realized return |
| Similar Case Memory | embeddings later | prior reports matching theme/cycle/technical structure |

## TradingProfile Fields

- `style`: user style label, e.g. `趋势+价值混合`
- `risk_level`: low, medium, high
- `holding_period`: intraday, days, weeks, months
- `preferred_setups`: setups to boost in report framing
- `avoid_patterns`: setups to downgrade
- `favorite_themes`: themes to monitor more closely
- `review_rules`: user's own rules learned from feedback

## Write Path

Every analysis run should append one event:

```json
{
  "event_type": "analysis_report",
  "symbol": "600519.SH",
  "analysis_date": "2026-07-10",
  "created_at": "2026-07-11T...",
  "payload": {
    "report": {},
    "profile_version": 1
  }
}
```

Feedback is written as separate events so the agent can compare expectation and outcome later.

## Read Path

Before each analysis:

1. Load `TradingProfile`.
2. Retrieve recent reports for the same symbol.
3. Retrieve similar reports by theme/market stage. In local v2 this is keyword matching; in production v2 this uses `pgvector`.
4. Pass a compact memory context to the reasoning layer and final report builder.

## Learning Policy

- Explicit user preferences can update `TradingProfile` immediately.
- Outcome-based rules require evidence: at least one feedback event with date, symbol, outcome, and reason.
- The system should phrase learned rules as "based on your history" and keep original feedback traceable.

## MVP Runtime Behaviour

`LocalMemoryStore` implements the local version now:

- Every CLI analysis loads the current `TradingProfile` and adds a `个人交易画像适配` insight to the report.
- Explicit `preference` feedback recognizes only a small allowlist of clear phrases such as `不追高`, `低吸`, and `趋势回踩`; it never infers a preference from a report or outcome.
- Explicit `rule` feedback is copied to `review_rules` only when `learned_rule` is supplied.
- `outcome` feedback remains append-only evidence. It does not automatically alter the user's profile.

## Portable Memory Bundle

`LocalMemoryStore.export_bundle()` produces a versioned JSON document containing:

- `trading_profile`: style, risk appetite, preferred and avoided setups, and review rules;
- `events.analysis`: full research reports;
- `events.feedback`: preference, correction, rule, and outcome evidence;
- `events.interaction`: compact summaries of each question and completed report.

`import_bundle()` validates the format and merges event collections by UUID. It does not replace local history or duplicate an existing event. This makes `trading-agents-memory.json` the only personal file a user needs to copy between computers.
