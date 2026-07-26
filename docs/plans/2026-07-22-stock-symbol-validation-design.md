# Stock symbol validation design

## Problem

The watchlist accepted `00国际复材`, normalized it to `00国际复材.SH`, and then routed it to Shanghai quote providers. The value is not a valid security code. The fallback happened because unknown input was assigned to the configured default exchange without validating that the code contained exactly six ASCII digits.

## Decision

- Accept exactly six ASCII digits with an optional configured exchange suffix, with or without the dot.
- Normalize full-width punctuation, whitespace, and common invisible copy/paste characters before validation.
- Infer the exchange from configured stock and convertible-bond prefixes.
- Reject unsupported prefixes and explicit suffixes that conflict with the inferred exchange.
- Never route malformed input to a default exchange.
- Remove malformed legacy watchlist rows while preserving and deduplicating valid rows.
- Apply the same structural validation to analysis, watchlist, and position forms before sending a request.
- Do not use HTML `maxlength` or `pattern` as an authority: pasted invisible characters must be sanitized by JavaScript before the backend performs authoritative validation.
- Keep explicit exchange semantics strict: a sanitized `301526SH` remains invalid because the code belongs to SZ.

## Verification

- Valid SH, SZ, BJ, and convertible-bond symbols retain their current normalization.
- `00国际复材.SH`, unsupported suffixes, short codes, and mismatched suffixes raise a clear error.
- Loading a legacy watchlist removes invalid rows and rewrites the repaired file.
- The web service rejects invalid additions and accepts `301526` as `301526.SZ`.
- `301526SZ`, `301526.SZ`, and `301526\u200cSZ` all normalize to `301526.SZ`.
