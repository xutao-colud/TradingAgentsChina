# ADR 006: Persist Provider Snapshots Before Quality-Gated Normalization

## Status

Accepted — 2026-07-13

## Context

The authenticated Tushare adapter already exposed 龙虎榜 and 融资融券 records, and AkShare supplied public supplemental data. The system could not replay the vendor response that produced a finding, detect payload tampering, or distinguish a valid empty result from a provider exception. It also trusted normalized values without checking source date, required fields, finite numbers, non-negative balances, or OHLC invariants.

An official-field review found a concrete unit defect: Tushare `top_list.net_amount` and `top_inst.net_buy` are already expressed in yuan, but `top_list.net_amount` was multiplied by 10,000 during normalization.

## Decision

1. `ProviderAdapter` defines common capability, raw-snapshot, and quality-report methods. Full providers continue to implement `MarketDataProvider`; supplemental providers implement the same adapter boundary.
2. Production composition injects one `LocalRawSnapshotStore` into Tushare and AkShare. Standalone tests default to an in-memory store.
3. Every provider call captures the response before normalization, including failed calls. Request secrets are redacted according to runtime configuration.
4. Snapshots are append-only JSON records with provider/interface metadata, request time, analysis date, symbol, source records, status, and SHA-256 integrity hash.
5. Normalized daily prices, 龙虎榜, and 融资融券 records pass configured deterministic validation. Invalid records never reach an Agent and are never replaced with a neutral fact.
6. Quality reports are attached to `AnalysisReport` and feed data readiness. A valid fallback daily-price provider can satisfy the blocking price gate while the failed primary remains visible as a non-blocking warning.
7. Tushare 龙虎榜 amounts retain the official yuan unit with no additional multiplier.

## Consequences

- Reports can identify exactly which raw provider calls were used and replay their inputs.
- Optional data failures remain observable without necessarily blocking unrelated research dimensions.
- Raw snapshots consume local disk and require retention/backup policy before SaaS deployment.
- A persisted hash detects accidental or malicious mutation but does not authenticate the upstream vendor; signed or WORM storage remains a future production option.
