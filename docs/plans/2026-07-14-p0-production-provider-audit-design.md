# P0 production-provider audit design

## Goal

Close the remaining path that can silently substitute sample facts, expose the deterministic DuPont components on the fundamental data contract, and distinguish market-wide northbound net flow from stock-level northbound holding changes.

## Decisions

- `ProductionMarketDataProvider` remains the only default full research provider and never uses sample data.
- The legacy Eastmoney provider may use a caller-supplied fallback, but its default fallback is the production provider rather than `SampleMarketDataProvider`. Provider failure must remain unavailable unless another real provider succeeds.
- `FundamentalSnapshot` carries `net_profit_margin`, `asset_turnover`, and `equity_multiplier` as optional derived facts. Tushare computes them from the same point-in-time income and balance-sheet records used by the report. Missing statements produce `None`, not zero.
- Market-wide northbound net flow comes from Tushare `moneyflow_hsgt.north_money` and is stored separately from per-stock `hk_hold` changes. The documented source unit is millions of yuan, normalized to yuan exactly once.
- The new northbound market-flow record passes date, finite-number, uniqueness, raw-snapshot, and evidence checks before it can affect the capital-flow explanation.
- Missing turnover in a money-flow snapshot remains `None`; it is not converted to zero and therefore cannot suppress a turnover-risk warning.

## Verification

Tests cover the no-sample Eastmoney failure path, explicit DuPont fields, northbound unit conversion and provenance, failed endpoint quality behavior, configuration validation, full workflow regression, and the complete test suite.
