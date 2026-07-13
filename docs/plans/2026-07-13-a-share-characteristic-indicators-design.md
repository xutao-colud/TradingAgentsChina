# A-share characteristic indicators design

## Goal

Add production-traceable A-share limit-structure, AH-premium, and turnover-continuity evidence without inventing missing observations or embedding market thresholds in code.

## Data contracts

- Tushare `limit_list_d` remains the single source for sealed limit-ups (`U`), failed breakouts (`Z`), first seal time, open count, and consecutive-board count.
- Seal rate is `U / (U + Z)` and failed-breakout rate is `Z / (U + Z)`. Both are emitted so their shared denominator can be audited.
- One-price limit-ups require an allowed opening seal time from runtime configuration and `open_times == 0`.
- The board ladder is aggregated into runtime-configured buckets. No board threshold is embedded in Python.
- Tushare `stk_ah_comparison` supplies the aligned A/H symbol pair, closes, ratio, and premium. No local symbol mapping or inferred FX rate is allowed.
- Turnover continuity is derived only from dated `DailyPrice.turnover_rate` values and the configured windows.

## Reasoning flow

Providers normalize and quality-check facts. Deterministic skills interpret the facts. Market sentiment consumes the historical limit structure, while the investment committee admits only same-date, traceable signals. Missing entitlement, missing fields, date mismatch, inconsistent seal/breakout rates, or missing evidence sources causes explicit rejection or unavailability rather than a neutral value.

## Verification

Tests cover exact seal/breakout complementarity, bounds, one-price detection, continuously exhaustive board buckets, AH source coverage/symbol/date/ratio quality, missing AH records, turnover direction and insufficient history, committee admission, runtime configuration validation, and end-to-end workflow output.
