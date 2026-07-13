# Committee signal integration design

## Problem

The workflow collects dragon-tiger disclosures, margin financing, northbound
holdings, tiered money flow, and intraday order-book observations, but the
investment committee only sees legacy agent scores and generic skill scores.
The court therefore cannot cite, challenge, or route the new evidence.

## Selected approach

Pass typed provider snapshots, quality reports, evidence sources, and the
analysis date into the committee. A private committee evidence view normalizes
each signal into:

- admission status: admitted, unavailable, or rejected;
- observed value and deterministic numeric fields;
- source ids and source time;
- quality status and limitations.

Missing, stale, untraceable, or quality-failed evidence creates no score
adjustment. It is exposed as an evidence gap instead of being converted to a
neutral zero.

## Routing

- Dragon-tiger disclosure: aggressive hot-money; disclosed institution net as
  secondary evidence for institutional growth.
- Margin financing activity: trend-capacity and institutional growth.
- Northbound holding change: institutional growth and value-dividend.
- Tiered money-flow divergence: aggressive hot-money, trend-capacity, and
  institutional growth.
- Intraday order-book imbalance: aggressive hot-money, trend-capacity, and
  reversal observation.

All weights, scales, required quality states, and direction impacts live in the
runtime configuration. These are evidence-fit adjustments, not return
probabilities or trade instructions.

## Failure handling

- A failed semantic quality report rejects the related disclosure.
- A source date different from the analysis date rejects the signal.
- A missing source id rejects the signal as untraceable.
- An empty but successful dragon-tiger query means no disclosed record, not no
  short-term capital activity.
- Intraday order-book imbalance remains cancellable-order evidence and carries
  its existing limitation into cross-examination.

## Verification

Tests compare otherwise identical committees with positive and negative signal
bundles, assert only intended factions move, assert source/time metadata reaches
score adjustments, and assert quality-failed or stale signals have zero impact.
