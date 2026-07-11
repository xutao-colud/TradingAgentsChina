from __future__ import annotations

import unittest

from app.analytics.strategy_performance import summarize_strategy_outcomes
from app.saas.contracts import StrategyOutcomeRecord, TenantContext


class StrategyPerformanceTest(unittest.TestCase):
    def test_insufficient_samples_remain_exploratory(self) -> None:
        records = [
            StrategyOutcomeRecord("tenant-a", "user-a", "r1", "trend_core", 60, 2.0, 10, True),
            StrategyOutcomeRecord("tenant-a", "user-a", "r2", "trend_core", 80, 5.0, 10, True),
        ]
        summary = summarize_strategy_outcomes(records, min_sample_size=30)[0]
        self.assertEqual(summary.evidence_status, "exploratory")
        self.assertIn("不对战法有效性", summary.interpretation)

    def test_consent_is_required_and_positive_association_is_not_causal(self) -> None:
        records = [
            StrategyOutcomeRecord("tenant-a", "user-a", f"r{index}", "trend_core", index, index / 10, 10, True)
            for index in range(1, 31)
        ] + [StrategyOutcomeRecord("tenant-a", "user-a", "excluded", "trend_core", 99, 99, 10, False)]
        summary = summarize_strategy_outcomes(records, min_sample_size=30)[0]
        self.assertEqual(summary.eligible_sample_size, 30)
        self.assertEqual(summary.evidence_status, "observational_positive_association")
        self.assertIn("不代表战法导致收益", summary.limitations[0])

    def test_tenant_context_requires_roles(self) -> None:
        context = TenantContext("tenant-a", "user-a")
        with self.assertRaises(PermissionError):
            context.require("admin")
