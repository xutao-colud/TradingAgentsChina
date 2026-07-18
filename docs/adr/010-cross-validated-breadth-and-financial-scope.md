# ADR 010: Cross-validated market breadth and explicit financial scope

- Status: accepted
- Date: 2026-07-16

## Context

An index can rise while most stocks fall because a small number of high-weight or high-turnover names dominate the index. Treating the index, advance/decline count, or turnover as an independent market-regime fact therefore creates false confidence. The Sina fallback also lacks an official historical limit-up pool, but its current quote snapshot exposes previous close, open, high, low, last price and change percentage.

Financial abstracts expose useful structured fields but do not replace report notes or industry-cycle evidence. Asset turnover and non-recurring-profit analysis must not be produced when their source fields are absent.

## Decision

1. Providers publish three additional observable cross-section facts: median stock return, amount-weighted return and top-N turnover concentration.
2. A deterministic breadth-confirmation calculation compares index direction, stock-return median, advance ratio, amount-weighted return and limit-up/down balance before the market Agent increases confidence.
3. The Sina fallback derives only current-session touched-limit, sealed-limit, broken-limit and one-price-limit facts from quoted OHLC and previous close. It does not infer consecutive-board ladders, yesterday premium or sentiment history.
4. Financial snapshots expose deducted net income, the net-versus-deducted difference and its ratio when both inputs exist. Providers attach explicit scope limitations.
5. DuPont asset turnover is calculated only when revenue and total assets are both available and valid. Missing inputs remain named, traceable gaps; they are never replaced with zero or a neutral score.
6. Verified-cache schema version is advanced so older snapshots cannot silently bypass the new evidence contract.

## Consequences

- Market-regime confidence is reduced when index strength conflicts with equal-weight breadth or limit feedback.
- Sina improves current-session fallback coverage without pretending to provide historical sentiment structure.
- Reports can distinguish operating profit quality from one-off profit effects when the provider exposes deducted profit.
- Full report notes and industry-cycle conclusions remain separate evidence requirements.
