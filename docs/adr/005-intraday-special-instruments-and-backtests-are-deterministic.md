# ADR 005: Intraday, special-instrument and backtest logic is deterministic

## Status

Accepted on 2026-07-13.

## Decision

Third-priority market features are implemented outside the LLM:

- intraday bars and order-book observations retain provider time and source ids;
- order-flow labels are observational heuristics, never claims about a hidden actor's intent;
- new-stock, secondary-new-stock and convertible-bond constraints are derived from dated instrument metadata;
- backtest signals are decided on bar close and filled no earlier than the next eligible bar open;
- T+1, daily limits, liquidity, commission, stamp duty and slippage are explicit execution assumptions;
- backtest results are empirical sample descriptions, not promised or fabricated win rates.

When a provider cannot supply required fields, the module returns `unavailable` or `insufficient_evidence`. It must not fill missing real-time data with sample values.
