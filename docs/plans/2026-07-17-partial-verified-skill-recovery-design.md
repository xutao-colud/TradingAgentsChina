# Partial verified skill recovery

## Problem

Several UI skills discarded an entire verified dataset when a secondary field was missing. A real sealed-limit rate, broken-board rate, or vendor main-flow value therefore appeared as generic `数据不足`, while missing fields were indistinguishable from failed sources.

## Design

- Keep a hard gate for the minimum evidence needed by the named conclusion.
- Admit independently verified observations even when optional dimensions are absent.
- Mark the result `partial` and name every missing dimension.
- Never convert a missing value to zero.
- Do not infer board-ladder strength from sealed-board data, or infer accumulation/distribution from a single vendor flow measure.
- Replay integrity-checked local snapshots for multi-day continuity when the upstream provider is temporarily unavailable.
- Reuse one verified Sina trade-print response for both trade-direction flow and intraday bars.

## Expected UI behavior

The user sees a scoped conclusion such as `封板分歧（梯队待核验）`, `一般（部分核验）`, or `单口径净流入观察`. Truly absent core evidence remains `数据不足`.

## Verification

Unit tests cover partial market evidence, partial money-flow evidence, cache-backed history, and reuse of a single public trade-print fetch.
