# Report role-language design

## Goal

Replace user-facing technical labels such as `资金流 Agent` and `Judge` with a consistent court-style research vocabulary, without changing internal identifiers used by scoring, replay, backtests, and reputation statistics.

## Design

- Keep `AgentFinding.agent` unchanged inside the deterministic workflow and memory store.
- Configure the public role glossary under `reporting.presentation`.
- Translate only at presentation boundaries: API responses, CLI JSON, Markdown, evidence briefs, and model context.
- Translate nested human-readable strings so committee score explanations do not leak internal labels.
- Preserve provider ids, source ids, dataset names, and configuration paths.

## Verification

- Internal reports still use stable Agent keys.
- Public payloads expose configured court-style roles.
- Decision brief and model context use the same glossary.
- The committee heading uses the configured chief-judge title.
- Configuration validation rejects incomplete or duplicate role mappings.
