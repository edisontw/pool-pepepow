from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "pool-core"))

from rpc_fixture_server import RpcFixtureServer
from config import load_config


REPO_ROOT = Path(__file__).resolve().parents[1]
PRODUCER_PATH = REPO_ROOT / "apps" / "pool-core" / "producer.py"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "daemon"
REINDEX_FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "daemon-reindex"


class ProducerTests(unittest.TestCase):
    def test_load_config_separates_estimation_difficulty_from_share_difficulty(self):
        original = os.environ.copy()
        try:
            os.environ["PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY"] = "1e-08"
            os.environ["PEPEPOW_POOL_CORE_ESTIMATED_HASHRATE_ASSUMED_SHARE_DIFFICULTY"] = (
                "1e-11"
            )
            config = load_config()
            self.assertEqual(config.hashrate_assumed_share_difficulty, 1e-08)
            self.assertEqual(
                config.estimated_hashrate_assumed_share_difficulty,
                1e-11,
            )

            del os.environ[
                "PEPEPOW_POOL_CORE_ESTIMATED_HASHRATE_ASSUMED_SHARE_DIFFICULTY"
            ]
            fallback_config = load_config()
            self.assertEqual(
                fallback_config.estimated_hashrate_assumed_share_difficulty,
                1e-08,
            )
        finally:
            os.environ.clear()
            os.environ.update(original)

    def test_producer_writes_runtime_snapshot_while_unsynced(self):
        server = RpcFixtureServer(REINDEX_FIXTURE_DIR)
        server.start()

        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                snapshot_path = Path(tmp_dir) / "runtime.json"
                share_log_path = Path(tmp_dir) / "activity-events.jsonl"
                now = datetime.now(timezone.utc).replace(microsecond=0)
                share_log_path.write_text(
                    "\n".join(
                        [
                            json.dumps(
                                {
                                    "timestamp": (
                                        now - timedelta(minutes=4)
                                    ).isoformat().replace("+00:00", "Z"),
                                    "wallet": "PEPEPOWWalletAlpha111111111111",
                                    "worker": "rig01",
                                    "status": "accepted",
                                }
                            ),
                            json.dumps(
                                {
                                    "timestamp": (
                                        now - timedelta(minutes=3)
                                    ).isoformat().replace("+00:00", "Z"),
                                    "login": "PEPEPOWWalletAlpha111111111111.rig02",
                                    "status": "accepted",
                                }
                            ),
                            json.dumps(
                                {
                                    "timestamp": (
                                        now - timedelta(minutes=2)
                                    ).isoformat().replace("+00:00", "Z"),
                                    "wallet": "PEPEPOWWalletBeta222222222222",
                                    "worker": "box01",
                                    "status": "rejected",
                                }
                            ),
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
                env = os.environ.copy()
                env.update(
                    {
                        "PEPEPOWD_RPC_URL": server.url,
                        "PEPEPOWD_RPC_USER": "test-user",
                        "PEPEPOWD_RPC_PASSWORD": "test-password",
                        "PEPEPOWD_RPC_TIMEOUT_SECONDS": "2",
                        "PEPEPOW_POOL_CORE_SNAPSHOT_OUTPUT": str(snapshot_path),
                        "PEPEPOW_POOL_CORE_RECENT_BLOCKS_LIMIT": "3",
                        "PEPEPOW_POOL_CORE_STRATUM_HOST": "pool.example.com",
                        "PEPEPOW_POOL_CORE_STRATUM_PORT": "3333",
                        "PEPEPOW_POOL_CORE_ACTIVITY_LOG_PATH": str(share_log_path),
                        "PEPEPOW_POOL_CORE_ACTIVITY_WINDOW_SECONDS": "900",
                        "PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY": "1e-08",
                        "PEPEPOW_POOL_CORE_ESTIMATED_HASHRATE_ASSUMED_SHARE_DIFFICULTY": "1e-11",
                    }
                )
                subprocess.run(
                    [sys.executable, str(PRODUCER_PATH), "--once"],
                    check=True,
                    cwd=str(PRODUCER_PATH.parent),
                    env=env,
                )

                payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
                self.assertEqual(payload["meta"]["producer"], "pepepow-pool-core")
                self.assertEqual(payload["meta"]["blockFeedKind"], "observed-network-blocks")
                self.assertEqual(payload["meta"]["chainState"], "reindexing")
                self.assertEqual(payload["meta"]["activityMode"], "testing-local-ingest")
                self.assertEqual(payload["meta"]["activityDataStatus"], "live")
                self.assertTrue(payload["meta"]["activityDerivedFromShares"])
                self.assertFalse(payload["meta"]["blockchainVerified"])
                self.assertEqual(payload["meta"]["assumedShareDifficulty"], 1e-11)
                self.assertFalse(payload["meta"]["degraded"])
                self.assertEqual(len(payload["blocks"]), 1)
                self.assertGreater(payload["pool"]["poolHashrate"], 0)
                self.assertEqual(payload["pool"]["activeMiners"], 2)
                self.assertEqual(payload["pool"]["activeWorkers"], 3)
                self.assertEqual(len(payload["pool"]["workerDistribution"]), 2)
                self.assertEqual(payload["network"]["height"], 0)
                self.assertFalse(payload["network"]["synced"])
                self.assertIn("PEPEPOWWalletAlpha111111111111", payload["miners"])
        finally:
            server.stop()

    def test_producer_marks_reindex_chain_state(self):
        server = RpcFixtureServer(REINDEX_FIXTURE_DIR)
        server.start()

        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                snapshot_path = Path(tmp_dir) / "runtime.json"
                env = os.environ.copy()
                env.update(
                    {
                        "PEPEPOWD_RPC_URL": server.url,
                        "PEPEPOWD_RPC_USER": "test-user",
                        "PEPEPOWD_RPC_PASSWORD": "test-password",
                        "PEPEPOWD_RPC_TIMEOUT_SECONDS": "2",
                        "PEPEPOW_POOL_CORE_SNAPSHOT_OUTPUT": str(snapshot_path),
                        "PEPEPOW_POOL_CORE_RECENT_BLOCKS_LIMIT": "1",
                    }
                )
                subprocess.run(
                    [sys.executable, str(PRODUCER_PATH), "--once"],
                    check=True,
                    cwd=str(PRODUCER_PATH.parent),
                    env=env,
                )

                payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
                self.assertEqual(payload["meta"]["chainState"], "reindexing")
                self.assertLess(payload["meta"]["chainVerificationProgress"], 0.01)
                self.assertEqual(payload["pool"]["poolStatus"], "syncing")
            return
        finally:
            server.stop()

    def test_producer_preserves_existing_snapshot_when_primary_rpc_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            snapshot_path = Path(tmp_dir) / "runtime.json"
            original_payload = {"generatedAt": "2026-01-01T00:00:00Z"}
            snapshot_path.write_text(
                json.dumps(original_payload), encoding="utf-8"
            )

            env = os.environ.copy()
            env.update(
                {
                    "PEPEPOWD_RPC_URL": "http://127.0.0.1:1",
                    "PEPEPOWD_RPC_USER": "test-user",
                    "PEPEPOWD_RPC_PASSWORD": "test-password",
                    "PEPEPOWD_RPC_TIMEOUT_SECONDS": "1",
                    "PEPEPOW_POOL_CORE_SNAPSHOT_OUTPUT": str(snapshot_path),
                    "PEPEPOW_POOL_CORE_RECENT_BLOCKS_LIMIT": "3",
                }
            )

            result = subprocess.run(
                [sys.executable, str(PRODUCER_PATH), "--once"],
                check=False,
                cwd=str(PRODUCER_PATH.parent),
                env=env,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual(payload, original_payload)
