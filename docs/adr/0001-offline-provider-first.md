# ADR-0001: Start with an Offline Sample Provider

## Status
Accepted

## Context
The MVP needs to prove the A-share research workflow before it depends on external market-data services. Free public data sources can change response shapes, add limits, or fail without notice. Tushare may require tokens and points, while AkShare and Eastmoney adapters need separate validation.

## Decision
Build the first runnable version with a `MarketDataProvider` interface and a `SampleMarketDataProvider`. All agents consume normalized dataclasses, not raw vendor responses. Real AkShare, Tushare, Eastmoney, or cninfo providers can be added later without changing the agent workflow.

## Consequences

### Positive
- The MVP runs without network access or credentials.
- Tests are deterministic.
- The data boundary is explicit, making future provider swaps safer.
- Agent reasoning is separated from deterministic calculations.

### Negative
- First reports use sample data and are not live market analysis.
- Provider adapters still need follow-up work before production use.

### Neutral
- The CLI and workflow are ready for real data once provider implementations exist.

## Alternatives Considered

**Bind directly to AkShare first**
- Rejected for MVP because network/data-shape instability could block core workflow validation.

**Clone the full TradingAgents graph immediately**
- Rejected for MVP because A-share rules, provider normalization, and report traceability are higher priority than a large orchestration surface.

