from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from tempfile import TemporaryDirectory

from app.data.quality import validate_raw_snapshot
from app.data.raw_snapshots import (
    LocalRawSnapshotStore,
    build_raw_snapshot,
    snapshot_is_intact,
)


class RawSnapshotTest(unittest.TestCase):
    def test_snapshot_redacts_credentials_and_round_trips_with_integrity(self) -> None:
        snapshot = build_raw_snapshot(
            provider="tushare",
            interface="margin_detail",
            request_params={
                "ts_code": "600519.SH",
                "trade_date": "20260710",
                "token": "secret",
                "auth": {"api_key": "nested-secret"},
            },
            records=[{"trade_date": "20260710", "rzye": 1000}],
            status="success",
            requested_at=datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(snapshot.request_params["token"], "[REDACTED]")
        self.assertEqual(snapshot.request_params["auth"]["api_key"], "[REDACTED]")
        self.assertEqual(snapshot.analysis_date, "2026-07-10")
        self.assertEqual(snapshot.source_record_count, 1)
        self.assertFalse(snapshot.truncated)
        self.assertTrue(snapshot_is_intact(snapshot))

        with TemporaryDirectory() as directory:
            store = LocalRawSnapshotStore(directory)
            store.save(snapshot)
            restored = store.list()
            restored_by_id = store.get(snapshot.snapshot_id)

        self.assertEqual(restored, [snapshot])
        self.assertEqual(restored_by_id, snapshot)
        self.assertEqual(validate_raw_snapshot(restored[0]).status, "passed")

    def test_tampered_snapshot_fails_hash_validation(self) -> None:
        snapshot = build_raw_snapshot(
            provider="akshare",
            interface="stock_zh_a_hist",
            request_params={"symbol": "600519", "end_date": "20260710"},
            records=[{"收盘": 100}],
            status="success",
        )
        tampered = replace(snapshot, records=[{"收盘": 999}])

        self.assertFalse(snapshot_is_intact(tampered))
        report = validate_raw_snapshot(tampered)
        self.assertEqual(report.status, "failed")
        self.assertEqual(report.issues[0].code, "snapshot_integrity_failure")


if __name__ == "__main__":
    unittest.main()
