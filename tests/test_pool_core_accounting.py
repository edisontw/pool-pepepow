from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

POOL_CORE_DIR = Path(__file__).resolve().parents[1] / "apps" / "pool-core"
sys.path.insert(0, str(POOL_CORE_DIR))

from accounting import build_activity_snapshot  # noqa: E402
from activity_ingest import load_share_events, parse_share_event  # noqa: E402
from producer import SnapshotProducer  # noqa: E402


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "shares"
    / "activity-events.jsonl"
)


class PoolCoreAccountingTests(unittest.TestCase):
    def test_accounting_parses_jsonl_and_aggregates_active_counts(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            share_log_path = Path(tmp_dir) / "activity-events.jsonl"
            share_log_path.write_text(
                FIXTURE_PATH.read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            load_result = load_share_events(share_log_path)
            activity = build_activity_snapshot(
                load_result.events,
                activity_window_seconds=900,
                warning_count=len(load_result.warnings),
                now=datetime(2026, 4, 13, 10, 14, 0, tzinfo=timezone.utc),
            )

            self.assertEqual(activity.data_status, "live")
            self.assertEqual(activity.active_miners, 2)
            self.assertEqual(activity.active_workers, 3)
            self.assertEqual(activity.last_share_at, "2026-04-13T10:13:30Z")
            alpha = activity.miners["PEPEPOWWalletAlpha111111111111"]
            self.assertEqual(alpha["summary"]["acceptedShares"], 2)
            self.assertEqual(alpha["summary"]["rejectedShares"], 1)
            self.assertEqual(alpha["summary"]["shareCount"], 3)
            self.assertEqual(alpha["summary"]["activeWorkers"], 2)
            self.assertIn("rolling", alpha["summary"])
            self.assertGreater(alpha["summary"]["hashrate"], 0)
            self.assertEqual(len(alpha["workers"]), 2)

    def test_accounting_ignores_old_events_outside_15m_window(self):
        event = parse_share_event(
            {
                "timestamp": "2026-04-13T09:00:00Z",
                "wallet": "PEPEPOWWalletOld333333333333",
                "worker": "old01",
            }
        )
        activity = build_activity_snapshot(
            [event],
            activity_window_seconds=900,
            now=datetime(2026, 4, 13, 10, 14, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(activity.data_status, "stale")
        self.assertEqual(activity.active_miners, 0)
        self.assertEqual(activity.active_workers, 0)
        self.assertIn("PEPEPOWWalletOld333333333333", activity.miners)

    def test_accounting_derives_hashrate_from_share_rate(self):
        event = parse_share_event(
            {
                "timestamp": "2026-04-13T10:10:00Z",
                "login": "PEPEPOWWalletAlpha111111111111.rig01",
            }
        )
        activity = build_activity_snapshot(
            [event],
            activity_window_seconds=900,
            now=datetime(2026, 4, 13, 10, 11, 0, tzinfo=timezone.utc),
        )

        miner_summary = activity.miners["PEPEPOWWalletAlpha111111111111"]["summary"]
        worker_summary = activity.miners["PEPEPOWWalletAlpha111111111111"]["workers"][0]
        self.assertGreater(miner_summary["hashrate"], 0)
        self.assertGreater(worker_summary["hashrate"], 0)
        self.assertEqual(miner_summary["rolling"]["5m"]["shareCount"], 1)

    def test_accounting_uses_estimation_difficulty_only_for_hashrate(self):
        event = parse_share_event(
            {
                "timestamp": "2026-04-13T10:10:00Z",
                "login": "PEPEPOWWalletAlpha111111111111.rig01",
            }
        )
        low_activity = build_activity_snapshot(
            [event],
            activity_window_seconds=900,
            now=datetime(2026, 4, 13, 10, 11, 0, tzinfo=timezone.utc),
            assumed_share_difficulty=1e-08,
        )
        high_activity = build_activity_snapshot(
            [event],
            activity_window_seconds=900,
            now=datetime(2026, 4, 13, 10, 11, 0, tzinfo=timezone.utc),
            assumed_share_difficulty=1e-05,
        )

        low_hashrate = low_activity.miners["PEPEPOWWalletAlpha111111111111"][
            "summary"
        ]["hashrate"]
        high_hashrate = high_activity.miners["PEPEPOWWalletAlpha111111111111"][
            "summary"
        ]["hashrate"]

        self.assertEqual(low_activity.assumed_share_difficulty, 1e-08)
        self.assertEqual(high_activity.assumed_share_difficulty, 1e-05)
        self.assertLess(low_hashrate, high_hashrate)

    def test_load_share_events_collects_warnings_for_malformed_lines(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            share_log_path = Path(tmp_dir) / "activity-events.jsonl"
            share_log_path.write_text(
                '{"timestamp":"2026-04-13T10:10:00Z","wallet":"wallet01"}\n'
                '{"timestamp":"bad","wallet":"wallet02"}\n'
                'not-json\n',
                encoding="utf-8",
            )

            load_result = load_share_events(share_log_path)

            self.assertEqual(len(load_result.events), 1)
            self.assertEqual(len(load_result.warnings), 2)

    def test_isolated_malformed_lines_warn_without_degrading_live_activity(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            share_log_path = root / "activity-events.jsonl"
            now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            share_log_path.write_text(
                f'{{"timestamp":"{now}","wallet":"wallet01","accepted":true}}\n'
                'not-json\n',
                encoding="utf-8",
            )
            producer = SnapshotProducer.__new__(SnapshotProducer)
            producer._config = SimpleNamespace(
                activity_log_path=share_log_path,
                activity_window_seconds=900,
                estimated_hashrate_assumed_share_difficulty=0.00025,
                activity_mode="stratum-share-ingest",
                snapshot_output_path=root / "activity-snapshot.json",
            )

            activity, degraded, error = producer._load_activity()

        self.assertFalse(degraded)
        self.assertIsNone(error)
        self.assertEqual(activity["warningCount"], 1)
        self.assertEqual(activity["dataStatus"], "live")


if __name__ == "__main__":
    unittest.main()
