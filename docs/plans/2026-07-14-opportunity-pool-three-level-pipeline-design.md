# Opportunity pool and three-level research pipeline

## Status

Accepted for implementation on 2026-07-14.

## Problem

Running the complete research workflow for every A-share is too slow and gives
low-quality candidates the same compute budget as positions, watchlist names,
and verified market anomalies.  A high score must also not be presented as a
fabricated success probability.

## Decision

Use one market-first, replayable pipeline:

1. **L1 deterministic scan**: combine positions, watchlist, explicit highlights,
   and verified radar movers.  Fetch lightweight snapshots in a bounded batch,
   then calculate evidence coverage, liquidity, flow, market fit, and
   `TradingProfile` fit without an LLM.
2. **L2 structured research**: run the existing deterministic agents and skills
   for the highest-ranked, sufficiently covered candidates, but do not convene
   the investment committee.
3. **L3 court review**: only candidates passing configured L1, data-readiness,
   evidence-chain, and L2 research thresholds enter the existing court-style
   investment committee.

The displayed score is an **opportunity evidence/fit score**, not a win rate or
return forecast. Missing data lowers coverage and can block promotion; it is
never replaced with a neutral fact.

## Persistence

- Keep the latest pool as an atomic JSON snapshot.
- Append every pipeline run to JSONL for replay.
- Save L2/L3 reports through the existing analysis memory and link their event
  ids from pool candidates.
- Preserve source id, source time, counter-evidence, risks, and invalidation
  conditions at every level.

## Performance boundaries

- One market-context request per run.
- One bounded snapshot batch for the candidate universe.
- No LLM calls in L1 or L2/L3 orchestration.
- Configured caps bound L1 candidates, L2 research, L3 court reviews, and worker
  concurrency.

## Alternatives considered

- **Full-market deep analysis**: rejected because provider calls and reasoning
  cost scale linearly with thousands of stocks.
- **Watchlist only**: rejected because it misses verified market anomalies.
- **LLM pre-screening**: rejected because facts and scoring must remain
  deterministic, testable, and traceable.
- **Opportunity score as win rate**: rejected because no point-in-time backtest
  evidence is implied by a current snapshot.

## Failure handling

- If market context is unavailable, the pool remains observable but cannot be
  promoted to L3.
- If a stock snapshot is unavailable or evidence coverage is below the
  configured minimum, the candidate is retained as insufficient evidence or
  excluded from promotion.
- One candidate failure does not abort the entire batch; the error is persisted
  with that candidate.

