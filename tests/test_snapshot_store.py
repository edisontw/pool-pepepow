from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from store import SnapshotStore, SnapshotUnavailableError  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[1]
FALLBACK_SNAPSHOT_PATH = (
    REPO_ROOT / "apps" / "api" / "data" / "mock" / "pool-snapshot.json"
)
DEFAULT_ACTIVITY_SNAPSHOT_PATH = Path("/tmp/pepepow-activity-snapshot.json")


def load_snapshot(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class SnapshotStoreTests(unittest.TestCase):
    def test_runtime_snapshot_is_preferred(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "runtime.json"
            runtime_snapshot = load_snapshot(FALLBACK_SNAPSHOT_PATH)
            runtime_snapshot["meta"]["degraded"] = False
            runtime_snapshot["generatedAt"] = "2999-01-01T00:00:00Z"
            runtime_path.write_text(
                json.dumps(runtime_snapshot), encoding="utf-8"
            )

            store = SnapshotStore(
                runtime_snapshot_path=runtime_path,
                fallback_snapshot_path=FALLBACK_SNAPSHOT_PATH,
                activity_snapshot_path=DEFAULT_ACTIVITY_SNAPSHOT_PATH,
                cache_ttl_seconds=1,
                stale_after_seconds=180,
            )

            record = store.get_snapshot_record()
            self.assertEqual(record.source, "runtime")
            self.assertEqual(record.data_status, "live")
            self.assertFalse(record.degraded)
            self.assertIsInstance(record.meta, dict)

    def test_fallback_snapshot_is_used_when_runtime_missing(self):
        store = SnapshotStore(
            runtime_snapshot_path=Path("/tmp/not-there.json"),
            fallback_snapshot_path=FALLBACK_SNAPSHOT_PATH,
            activity_snapshot_path=DEFAULT_ACTIVITY_SNAPSHOT_PATH,
            cache_ttl_seconds=1,
            stale_after_seconds=180,
        )

        record = store.get_snapshot_record()
        self.assertEqual(record.source, "fallback")
        self.assertEqual(record.data_status, "fallback")
        self.assertTrue(record.degraded)
        self.assertIsNotNone(record.last_error)
        self.assertFalse(record.meta.get("minerLookupImplemented", True))

    def test_stale_runtime_snapshot_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "runtime.json"
            runtime_snapshot = load_snapshot(FALLBACK_SNAPSHOT_PATH)
            runtime_snapshot["meta"]["degraded"] = False
            runtime_snapshot["generatedAt"] = "2020-01-01T00:00:00Z"
            runtime_path.write_text(
                json.dumps(runtime_snapshot), encoding="utf-8"
            )

            store = SnapshotStore(
                runtime_snapshot_path=runtime_path,
                fallback_snapshot_path=FALLBACK_SNAPSHOT_PATH,
                activity_snapshot_path=DEFAULT_ACTIVITY_SNAPSHOT_PATH,
                cache_ttl_seconds=1,
                stale_after_seconds=180,
            )

            record = store.get_snapshot_record()
            self.assertEqual(record.source, "runtime")
            self.assertTrue(record.stale)
            self.assertTrue(record.degraded)
            self.assertEqual(record.data_status, "stale")

    def test_missing_all_snapshots_raises(self):
        store = SnapshotStore(
            runtime_snapshot_path=Path("/tmp/runtime-missing.json"),
            fallback_snapshot_path=Path("/tmp/fallback-missing.json"),
            activity_snapshot_path=DEFAULT_ACTIVITY_SNAPSHOT_PATH,
            cache_ttl_seconds=1,
            stale_after_seconds=180,
        )

        with self.assertRaises(SnapshotUnavailableError):
            store.get_snapshot_record()
