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
            os.environ["PEPEPOW_POOL_CORE_HASHRATE_ASSUMED_SHARE_DIFFICULTY"] = "0.005"
            os.environ["PEPEPOW_POOL_CORE_ESTIMATED_HASHRATE_ASSUMED_SHARE_DIFFICULTY"] = (
                "0.002"
            )
            config = load_config()
            self.assertEqual(config.hashrate_assumed_share_difficulty, 0.005)
            self.assertEqual(
                config.estimated_hashrate_assumed_share_difficulty,
                0.002,
            )

            del os.environ[
                "PEPEPOW_POOL_CORE_ESTIMATED_HASHRATE_ASSUMED_SHARE_DIFFICULTY"
            ]
            fallback_config = load_config()
            self.assertEqual(
                fallback_config.estimated_hashrate_assumed_share_difficulty,
                0.005,
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

    def test_producer_block_rewards_handling(self):
        from unittest.mock import MagicMock
        from producer import SnapshotProducer
        from config import PoolCoreConfig

        # Create a mock config
        config = PoolCoreConfig(
            coin_name="PEPEPOW",
            algorithm="hoohashv110-pepew",
            fee_percent=1.0,
            min_payout=10.0,
            stratum_host="127.0.0.1",
            stratum_port=3333,
            stratum_tls=False,
            stratum_bind_host="0.0.0.0",
            stratum_bind_port=3333,
            rpc_url="http://127.0.0.1:1",
            rpc_user="user",
            rpc_password="pwd",
            rpc_timeout_seconds=2,
            snapshot_output_path=Path("/tmp") / "snap.json",
            activity_snapshot_output_path=Path("/tmp") / "act.json",
            snapshot_interval_seconds=60,
            activity_snapshot_interval_seconds=1.0,
            rpc_cache_ttl_seconds=5,
            recent_blocks_limit=2,
            stale_after_seconds=180,
            producer_name="test-producer",
            activity_log_path=Path("/tmp") / "activity.jsonl",
            activity_window_seconds=900,
            activity_mode="testing-local-ingest",
            stratum_queue_maxsize=100,
            hashrate_assumed_share_difficulty=0.001,
            estimated_hashrate_assumed_share_difficulty=0.001,
            synthetic_job_interval_seconds=30.0,
            template_mode="synthetic",
            template_fetch_interval_seconds=15.0,
            template_job_ttl_seconds=180,
            template_job_cache_size=4,
            enable_real_submitblock=False,
            real_submitblock_max_sends=0,
            activity_log_rotate_bytes=1024,
            activity_log_retention_files=1,
            low_diff_share_full_log_every_n=1,
            notify_debug_capture_limit=0,
            stratum_notify_clean_jobs_legacy=False,
            stratum_wire_difficulty_scale=65536.0,
            stratum_vardiff_enabled=False,
            stratum_vardiff_initial_difficulty=0.1,
            stratum_vardiff_min_difficulty=0.0001,
            stratum_vardiff_max_difficulty=10.0,
            stratum_vardiff_target_share_interval_seconds=15.0,
            stratum_vardiff_retarget_interval_seconds=60.0,
            stratum_vardiff_min_shares=4,
            stratum_vardiff_fast_share_interval_seconds=8.0,
            stratum_vardiff_slow_share_interval_seconds=25.0,
        )

        rpc_client = MagicMock()
        rpc_client.get_blockchain_info.return_value = {
            "bestblockhash": "best_hash",
            "blocks": 100,
            "headers": 100,
            "verificationprogress": 0.9999
        }
        rpc_client.get_block_header.return_value = {
            "height": 100,
            "hash": "best_hash",
            "time": 123456789,
            "confirmations": 1
        }
        rpc_client.get_recent_block_headers.return_value = [
            {"height": 100, "hash": "best_hash", "time": 123456789, "confirmations": 1},
            {"height": 99, "hash": "prev_hash", "time": 123456700, "confirmations": 2}
        ]
        
        # Scenario 1: Both blocks have valid reward
        def get_block_mock(block_hash, verbosity=2):
            if block_hash == "best_hash":
                return {"tx": [{"vout": [{"value": 50000.0}]}]}
            else:
                return {"tx": [{"vout": [{"value": 45000.0}]}]}

        rpc_client.get_block = MagicMock(side_effect=get_block_mock)
        rpc_client.get_mining_info.return_value = {"networkhashps": 1000}
        rpc_client.get_network_info.return_value = {"warnings": ""}

        producer = SnapshotProducer(config, rpc_client)
        snap = producer.run_once()
        
        self.assertEqual(snap["blocks"][0]["reward"], 50000.0)
        self.assertEqual(snap["blocks"][1]["reward"], 45000.0)
        self.assertEqual(snap["network"]["reward"], 50000.0)

        # Scenario 2: One block fails to return reward / has no reward
        def get_block_mock_null(block_hash, verbosity=2):
            if block_hash == "best_hash":
                return {"tx": []} # lacks reward
            else:
                raise RuntimeError("RPC error") # failed request

        rpc_client.get_block = MagicMock(side_effect=get_block_mock_null)
        snap = producer.run_once()
        self.assertIsNone(snap["blocks"][0]["reward"])
        self.assertIsNone(snap["blocks"][1]["reward"])
        self.assertIsNone(snap["network"]["reward"])
