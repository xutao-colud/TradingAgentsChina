# ADR-008: Committee admits typed market signals

## Status

Accepted

## Context

The data layer collects dragon-tiger disclosures, margin financing, northbound
holdings, tiered money flow, and intraday order-book observations. The
investment committee previously received only legacy agent scores and generic
skills. New provider facts therefore could not appear in faction arguments,
cross-examination, or score explanations.

The committee must preserve the project's evidence-first rules: no missing
value may become a neutral fact, stale evidence must be rejected, and every
score adjustment must expose source ids and source time.

## Decision

Pass typed provider snapshots, evidence sources, semantic quality reports, and
the analysis date from the workflow into the committee. Normalize the five
signal families into a private evidence view with admission status, observed
values, source ids, source time, quality status, and limitations.

Only admitted evidence may adjust faction fit:

- dragon-tiger disclosure routes to aggressive hot-money, with institution
  seat net amount as secondary institutional-growth evidence;
- margin financing routes to trend-capacity and institutional growth;
- northbound holding change routes to institutional growth and value-dividend;
- tiered money flow routes to hot-money, trend-capacity, and institutional
  growth;
- order-book imbalance routes to hot-money, trend-capacity, and reversal.

All numeric scales and maximum impacts are runtime configuration. These scores
measure current evidence fit and are not probabilities or return forecasts.

## Consequences

### Positive

- Collected signals now affect only the investment schools that can explain
  their relevance.
- Court output exposes admitted, unavailable, and rejected evidence.
- Each new score adjustment carries source ids, as-of time, and admission
  status.
- Tushare and AkShare northbound records now have provider-specific semantic
  quality reports.

### Negative

- Some evidence overlaps with broad capital-flow agent scoring. Signal weights
  are intentionally small and should be calibrated through replay rather than
  treated as independent predictors.
- Additional committee inputs increase test and schema surface area.

### Neutral

- Missing optional signals do not change faction scores; rejected signals are
  preserved as risk challenges.

## Alternatives Considered

**Parse Agent evidence strings**

- Rejected because text parsing loses types, units, source identity, and stable
  failure semantics.

**Use only DragonTiger Agent and Skill scores**

- Rejected because aggregate scores cannot distinguish stale, untraceable, or
  provider-quality-failed evidence.

**Add every signal to a single global score**

- Rejected because the same observation has different relevance to hot-money,
  trend, institutional, value, and reversal playbooks.

## References

- [Committee signal integration design](../plans/2026-07-13-committee-signal-integration-design.md)
- [Provider snapshots and quality gates](006-provider-snapshots-and-quality-gates.md)
