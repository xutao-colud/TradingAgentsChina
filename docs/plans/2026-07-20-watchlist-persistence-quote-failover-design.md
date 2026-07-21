# Watchlist persistence and quote failover design

## Problem

- Alias or legacy rows can leave duplicate symbols in `watchlist.json`.
- `/api/market/refresh` drops watchlist rows when no quote is returned, so a provider failure looks like data loss.
- A prior implementation placed a recent cached close in the live-price slot, which made a traceable but stale value look current.

## Design

1. Canonicalize symbols at the persistence boundary, collapse duplicates on read, and use a process lock plus atomic replacement for watchlist writes.
2. Treat the watchlist as durable user state. Market refresh always returns every stored row and attaches an explicit quote state; quote availability never controls membership.
3. Route live quotes through Eastmoney, then the configured Tencent/Sina fallback order. Accept only a provider-declared real-time quote or a quote carrying today's provider timestamp.
4. Never place a prior-session cache or historical daily close in the live-price field. Historical evidence remains available to research reports, not the rolling quote component.
5. If no current source is admissible, retain the row with `data_status=unavailable` and no price.

## Acceptance criteria

- Re-adding `000725` and `000725.SZ` produces one row.
- Reloading the page reads the same persisted watchlist.
- Provider failure cannot make a watchlist row disappear.
- Tencent batch quote parsing preserves provider timestamp, source, price, previous close, percentage change, volume, and amount.
- Prior-session values are rejected from the rolling quote component even when they are integrity-verified.
- The full test suite remains green.
