# Committee signal depth design

## Problem

The committee already admits current-day dragon-tiger, margin, northbound,
tiered-flow, intraday, and aggregate capital-flow-continuity evidence. However,
dragon-tiger seat structure and historical after-effects remain text-only, while
northbound and margin streaks are blended into one continuity score. This makes
the court explanation less specific than the underlying data.

## Decision

- Preserve the typed evidence gate: missing, stale, untraceable, or
  quality-failed observations never change a faction score.
- Expose explicit context views for the dragon-tiger signal, northbound streak
  days, and margin-balance trend days. Missing values remain `None`, never zero.
- Route continuity components once: main-flow streak to aggressive hot money,
  margin-balance streak to trend capacity, and northbound holding streak to
  institutional growth. This prevents the same blended score from being counted
  by all three factions.
- Structure dragon-tiger seat types and per-seat historical after-effects in the
  agent output. Only seats explicitly classified through the configured,
  traceable hot-money mapping may affect the aggressive route.
- Historical seat evidence is observational. It reports sample size, horizon,
  median after-effect, and positive-return observation ratio; it is never called
  a win rate and never implies causality.

## Configuration and failure handling

All scales, maximum impacts, selected history horizon, minimum sample size, and
seat-type impacts live in `tradingos.default.json`. Runtime validation fails fast
for missing or invalid values. If seat history is unavailable or insufficient,
the committee records the gap and makes no adjustment.

## Verification

Tests cover structured seat history, no use of the word “win rate”, explicit
committee context fields, faction-specific continuity routing, source/time
traceability, and quality-gated historical seat evidence. The full unit suite,
compile check, JSON parse, and diff check must pass.
