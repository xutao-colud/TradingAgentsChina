# A-share risk coverage design

## Problem

The deterministic risk scanner currently covers trading status, earnings,
leverage, valuation, and cash-flow quality. It does not consume important
A-share-specific risk facts: important-shareholder reductions, exchange inquiry
letters, goodwill concentration, equity pledges, or sustained low liquidity.
Several existing thresholds and deductions are also embedded in Python.

## Decision

- Extend `StockProfile` with point-in-time reduction and inquiry facts, including
  source ids and observation dates. Extend `FundamentalSnapshot` with goodwill
  and pledge ratios and their provenance.
- Obtain goodwill from the point-in-time balance sheet and equity pledge ratio
  from Tushare `pledge_stat`. Important-shareholder reductions remain event
  facts from `stk_holdertrade`; inquiry letters remain official-announcement
  facts from the CNInfo-backed provider.
- Enrich the stock profile after provider composition, so risk facts use the
  same deduplicated signals, announcements, evidence sources, and quality
  reports as the final report.
- Preserve three states for every new check: triggered, passed, or insufficient.
  Missing or failed data never becomes a neutral fact and never creates a
  deduction.
- Compute liquidity from a configured trailing window of verified daily bars.
  Amount and turnover-rate thresholds reuse the central market-rule settings.
- Move scanner base score, grade boundaries, thresholds, lookback windows, and
  deductions to runtime configuration. Python contains calculation logic only.

## Evidence and failure handling

Every risk check exposes observed value, threshold, status, deduction, source
ids, source time, counterpoint, risk, and invalidation condition. A triggered
risk without traceable source evidence is downgraded to insufficient. Provider
permission failures and empty warning datasets remain visible in quality
reports.

## Verification

Tests cover provider ratio calculation and provenance, profile enrichment,
three-state missing-data behavior, every new configured deduction, rolling
liquidity calculations, runtime validation, and end-to-end workflow wiring.
The full test suite, compile check, JSON parse, and diff inspection must pass.
