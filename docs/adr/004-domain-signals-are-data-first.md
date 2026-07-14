# ADR 004: Domain Signals Are Data-First and Explicitly Incomplete When Needed

**Status:** Accepted

## Context

The original theme, technical, fundamental and sentiment implementations embedded a small industry map, a few moving averages, a financial snapshot, and single-day sentiment thresholds. That shape cannot distinguish a real concept relationship from a static label, nor disclose when the data necessary for a stronger claim is absent.

## Decision

Keep all calculations deterministic. Store theme aliases, industry defaults, technical periods and sentiment transition parameters in `tradingos.default.json`. Add optional typed fields for company concepts, financial statement values, peer benchmarks and sentiment history. Each analyzer returns an explicit "insufficient evidence" result when those inputs are absent; no proxy may be labelled as direct broker chip data or an industry ranking.

## Consequences

- Providers can improve independently without changing Agent logic.
- Historical replay remains deterministic when the input snapshot is persisted.
- The first production release will expose some incomplete fields because public/permissioned providers do not guarantee peer, concept and breadth history for every analysis date.
- More source records and data-quality requirements are necessary, but the system avoids fabricated sector or institutional conclusions.
