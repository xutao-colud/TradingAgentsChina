# ADR 009: Dataset-level provider failover and verified last-known-good cache

- Status: Accepted
- Date: 2026-07-16

## Context

The production provider composed Tushare and AkShare, but this was not true
operational redundancy. Tushare is unavailable without an entitlement token,
while several AkShare functions use Eastmoney endpoints internally. A failure
of the Eastmoney route therefore removed prices and current market breadth at
the same time. The workflow then emitted zero bars, missing required evidence,
and many repeated raw-request failures.

Retrying the same host cannot provide high availability. Returning sample or
synthetic neutral values would violate the evidence contract.

## Decision

Route each required dataset independently:

- daily prices: Tushare -> AkShare -> Tencent -> verified cache;
- fundamentals: Tushare -> Sina financial abstract -> verified cache;
- money flow: Tushare -> fresh verified cache -> THS individual fund flow ->
  Sina tick-direction observation -> Eastmoney order-size flow -> stale verified
  cache;
- current market breadth: Tushare -> fresh verified cache -> Sina market list
  plus Tencent index observation -> AkShare -> stale verified cache.

Only normalized data that passed the router's acceptance checks is written to
the verified cache. Cache entries include source type, actual `as_of`, save
time, schema version, and a SHA-256 integrity digest. Cache evidence is labelled
`verified_cache:<origin>`; it is never described as live.

The router uses per-provider/per-dataset circuit breakers. A failure of one
dataset does not disable unrelated capabilities from that provider. Raw request
failures remain auditable but are grouped in the user-facing readiness result.
When a fallback recovers a blocking dataset, upstream route failures become
non-blocking warnings.

Current-day daily bars, daily money flow, and completed-market snapshots may
legitimately have an `as_of` earlier than the wall-clock analysis date before
the session closes. The allowed calendar lag is configuration-driven and only
applies to today's analysis; historical requests remain strict.

THS's free individual-flow ranking can return a successful but partial market
list. The requested symbol must be present before that response is accepted;
empty or target-missing results are recorded as failures and are never cached
as zero flow. If vendor-defined flow is unavailable, Sina tick data supplies an
observable up-tick amount minus down-tick amount. That field is stored
separately and labelled as a price-direction observation; it is not scored or
displayed as institutional/main-capital flow.

Full-market AkShare queries such as northbound rankings are cache-only on the
interactive request path unless slow bulk refresh is explicitly enabled. This
prevents optional 50+ page downloads from blocking the four core evidence
datasets. A missing optional cache downgrades only that dimension.

## Consequences

- The system can continue research when Eastmoney is unreachable and Tushare
  is unconfigured, while preserving real source identities.
- The Sina breadth fallback is expensive on a cold start because it pages the
  full A-share universe. A short-lived verified cache and bounded concurrency
  prevent every research request from repeating that scan.
- Tencent historical bars do not publish historical amount and turnover in the
  selected contract. Those fields remain `None`, the quality report is a
  warning, and liquidity-dependent conclusions are downgraded rather than
  inferred.
- Sina market breadth does not provide broken-board or board-ladder history.
  Core breadth can be used, but short-line sentiment structure remains
  explicitly insufficient.
- No public endpoint can guarantee availability. Simultaneous cold-start
  failure still yields "insufficient evidence"; high availability reduces
  correlated failure without manufacturing facts.

## Rejected alternatives

- More retries against Eastmoney: correlated failure remains.
- Sample fallback in production: breaks provenance and can create false facts.
- Estimating historical turnover amount from close times volume: not an
  observed amount and would contaminate liquidity/risk conclusions.
- Treating a current quote as the requested historical date: introduces time
  mislabelling and look-ahead bias.
