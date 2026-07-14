# Production trial and configuration hardening

## Decision

Production entry points use `ProductionMarketDataProvider`; sample data is available only through an explicit sample workflow/provider. Missing production fields remain unknown and are excluded from scoring. Business thresholds and weights live in `config/tradingos.default.json` and are validated on startup.

## Evidence contract

Every accepted dataset must retain provider, interface, request time, analysis date, record count, content hash, quality result and snapshot id. Provider failures are persisted as error snapshots. Evidence from one provider operation is merged by source id and must not be overwritten by later signal collection.

## Trial acceptance criteria

- no implicit sample fallback;
- at least one real endpoint can produce a successful raw snapshot;
- missing credentials or entitlements produce `数据不足`, not neutral facts;
- a missing financial value is `None`, never numeric zero;
- market-regime failure blocks playbook selection and committee judgment;
- unit tests cover production defaults, evidence preservation and legacy threshold regression.

## Current external dependency

AkShare supplies public daily bars and a current-session market-breadth fallback (all-A-share quotes plus limit-up, limit-down and broken-limit pools). The fallback is never relabelled as historical data, and its bulk holder-trade snapshot has a configurable local reuse window. Full Tushare-backed fundamentals, historical market breadth, dragon-tiger, margin and other entitled datasets require a valid `TUSHARE_TOKEN`; without it the system remains fail-closed.

The 2026-07-14 live trial exited normally but the local proxy disconnected Eastmoney quote hosts. Limit-up, limit-down and broken-limit pools returned real records while daily bars, all-A-share quotes and index quotes failed. The report therefore remained `数据不足` and the committee refused judgment. This is the expected integrity behavior, not a passed production-data acceptance result.

The first trial also showed that AkShare's global holder-trade endpoint returned about 145,000 rows and dominated latency. It is now disabled by default through runtime configuration; Tushare's symbol-level holder-trade interface remains primary, and missing coverage stays unknown. A repeated live trial completed in under one minute instead of several minutes while preserving the same fail-closed decision behavior.
