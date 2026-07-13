# ADR 007: Build market regime from market-wide observations

- Status: Accepted
- Date: 2026-07-13

## Context

The Tushare provider previously returned an index change and index amount while
filling market breadth, limit-up/down counts, and the hot-money cycle with zero
or `unknown`. Those placeholders entered deterministic market skills as facts,
so missing data could be misclassified as a weak or cold market.

## Decision

1. Use Tushare `daily(trade_date=...)` for whole-market advance/decline breadth
   and whole-market turnover amount.
2. Use Tushare `limit_list_d(trade_date=...)` for limit-up, limit-down, broken
   boards, board height, first boards, and adjacent-day promotion statistics.
3. Build a configurable consecutive history and pass it through the existing
   deterministic sentiment-dynamics model before exposing a market regime.
4. Treat a successful empty response as an observed zero only where the source
   request succeeded. Request failure, missing fields, and incomplete history
   remain missing and block `market-001` evidence.
5. Persist raw snapshots and validate normalized market observations with a
   blocking `market_sentiment` quality report.
6. Extract optional policy themes from `major_news` with configuration-owned
   keywords. News entitlement failure does not synthesize a theme.
7. Do not use `limit_list_ths` in the SaaS path because its documentation states
   that commercial use requires separate authorization. Do not call an
   AkShare-style `stock_zt_pool` name through the Tushare adapter.

## Consequences

- Market-first strategy selection now has replayable breadth and sentiment
  evidence instead of placeholder values.
- Each analysis performs several date-scoped provider calls; provider rate
  limits and entitlements must be monitored and snapshots should support later
  caching/replay.
- `limit_list_d` does not include ST statistics, so reports preserve that scope
  limitation as a risk note.
- When any selected trading day is incomplete, the market gate returns
  `insufficient data` instead of selecting a playbook.
