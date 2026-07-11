# ADR 0002: Use Public Playbook Archetypes Instead of Named Trader Replication

## Status

Accepted — 2026-07-11

## Context

Users need switchable A-share styles inspired by hot-money and large-institution practices. Named individual or institution "replication" would be unverifiable, become stale, and encourage blind following.

## Decision

Ship a versioned library of public, rule-based archetypes. Each playbook declares its market regime, required evidence, disqualifiers, horizon, risk constraints, and review questions. The system assesses fit using deterministic Skills and returns a research/optimization note rather than an order instruction.

## Consequences

- Users can select and export an active playbook with their personal profile.
- New playbooks are pluggable code/data entries and require tests plus a stated hypothesis before promotion.
- The library does not claim to reproduce any named trader, fund, or non-public trading method.
- Historical results must be backtested with friction, out-of-sample checks, and A-share rule constraints before a playbook is labelled validated.
