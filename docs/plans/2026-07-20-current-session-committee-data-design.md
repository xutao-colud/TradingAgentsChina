# Current-session committee data recovery

## Problem

During a live trading day, a stock can have a complete 120-bar history and a
usable quote while the current market-breadth provider is temporarily
unavailable. The blocking `market-001` gate then prevents the court from
running, even though the missing fact is only the unfinished same-session
market cross-section.

## Decision

Keep the market-first gate and never synthesize breadth. After all configured
live market providers fail, production routing may replay the nearest prior
verified market-context cache within the configured `market-001` lag window.
The replay is allowed only when the requested analysis date is the current
date. It is labelled `latest_available`, retains its original observation
date and snapshot hash, and adds an explicit stale-market limitation.

Recovered provider failures become non-blocking quality warnings. Market
skills still reject the replay as same-session breadth, so offensive market
regime conclusions remain unavailable. Data readiness can nevertheless admit
the court at reduced reliability, allowing stock, fundamental, risk and other
verified evidence to be compared instead of returning an empty committee.

Realtime quotes with a non-positive price are invalid observations. The Web
service must continue to the independent Sina fallback rather than persist or
display a zero-price quote.

## Verification

- Replay is current-day only and bounded by runtime configuration.
- Original source date and integrity hash stay traceable.
- Current provider failure remains visible but non-blocking after recovery.
- A zero-price primary quote is replaced by a usable secondary quote.
- Full regression suite must pass before restarting the service.
