# TradingAgentsChina Codex Guide

Build this project as an A-share TradingOS, not a stock-prediction bot.

Core principles:

- Evidence first: every conclusion needs evidence, source id, source time, confidence, counterpoint, and risk.
- Memory first: every analysis, question, user preference, and outcome must be persistable and reviewable.
- User first: reports must adapt to `TradingProfile`; do not give every user the same answer.
- Strategy first: evaluate playbooks and market regimes before discussing action.
- Evolution first: prefer replayable feedback, strategy outcomes, and agent reputation over adding more agents.

Product rules:

- Do not promise returns, predict certain涨跌, or create automatic trade orders.
- Prefer "current evidence supports/does not support" over probability claims.
- It is acceptable and desirable to output "insufficient evidence" when signals conflict.
- Market regime comes before individual stock interpretation.
- China-market constraints are first-class: T+1, daily limits, ST, suspension, liquidity, announcements, policy cycles, theme lifecycle, money flow, sentiment cycle, and board differences.

Architecture rules:

- Facts and calculations stay outside the LLM. LLMs explain, compare, and summarize structured evidence.
- Data providers must implement `MarketDataProvider`; keep `SampleMarketDataProvider` as offline fallback.
- Skills are deterministic and independently testable.
- Agent findings must remain traceable through `EvidenceSource`.
- Investment committee should behave like a court: evidence, counter-evidence, risk challenge, judge summary. Avoid naive equal voting.
- New SaaS analytics must be consent-gated and observational only.

Preferred next investments:

1. Evidence-chain quality gates.
2. User memory and outcome replay.
3. Strategy performance by market regime.
4. Agent reputation by market regime.
5. Policy-industry-company knowledge graph.
