from __future__ import annotations

import json
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1] / "apps" / "api"
sys.path.insert(0, str(API_DIR))


def _load_module(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, API_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


api_config = _load_module("api_config", "config.py")
sys.modules["config"] = api_config
api_store = _load_module("api_store", "store.py")
sys.modules["store"] = api_store
api_app = _load_module("api_app", "app.py")

create_app = api_app.create_app
AppConfig = api_config.AppConfig


REPO_ROOT = Path(__file__).resolve().parents[1]
FALLBACK_SNAPSHOT_PATH = (
    REPO_ROOT / "apps" / "api" / "data" / "mock" / "pool-snapshot.json"
)


def load_snapshot(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def make_runtime_snapshot() -> dict:
    runtime_snapshot = load_snapshot(FALLBACK_SNAPSHOT_PATH)
    runtime_snapshot["meta"]["degraded"] = False
    runtime_snapshot["meta"]["stale"] = False
    runtime_snapshot["meta"]["schemaVersion"] = "2.2"
    runtime_snapshot["meta"]["chainState"] = "reindexing"
    runtime_snapshot["meta"]["chainVerificationProgress"] = 0.1
    runtime_snapshot["meta"]["minerLookupImplemented"] = True
    runtime_snapshot["meta"]["activityMode"] = "testing-local-ingest"
    runtime_snapshot["meta"]["activityDataSource"] = "local-jsonl-share-log"
    runtime_snapshot["meta"]["activityDataStatus"] = "live"
    runtime_snapshot["meta"]["activityWindowSeconds"] = 900
    runtime_snapshot["meta"]["activityLastShareAt"] = "2999-01-01T00:00:00Z"
    runtime_snapshot["meta"]["activityWarningCount"] = 0
    runtime_snapshot["meta"]["activityDerivedFromShares"] = True
    runtime_snapshot["meta"]["blockchainVerified"] = False
    runtime_snapshot["meta"]["assumedShareDifficulty"] = 1.0
    runtime_snapshot["meta"]["hashratePolicy"] = "share-rate-assumed-diff"
    runtime_snapshot["pool"]["poolStatus"] = "syncing"
    runtime_snapshot["pool"]["poolHashrate"] = 57266230.61333334
    runtime_snapshot["pool"]["activeMiners"] = 2
    runtime_snapshot["pool"]["activeWorkers"] = 3
    runtime_snapshot["pool"]["workerDistribution"] = [
        {
            "wallet": "PEPEPOW1KnownWalletAddress000000",
            "workers": 2,
            "activeWorkers": 2,
            "shares15m": 5,
            "hashrate": 57266230.61333334
        }
    ]
    runtime_snapshot["miners"] = {
        "PEPEPOW1KnownWalletAddress000000": {
            "summary": {
                "hashrate": 57266230.61333334,
                "pendingBalance": None,
                "totalPaid": None,
                "lastShareAt": "2999-01-01T00:00:00Z",
                "acceptedShares": 4,
                "rejectedShares": 1,
                "shareCount": 5,
                "activeWorkers": 2,
                "rolling": {
                    "1m": {
                        "windowSeconds": 60,
                        "shareCount": 1,
                        "acceptedShares": 1,
                        "rejectedShares": 0,
                        "hashrate": 71582788.26666667
                    },
                    "5m": {
                        "windowSeconds": 300,
                        "shareCount": 5,
                        "acceptedShares": 4,
                        "rejectedShares": 1,
                        "hashrate": 57266230.61333334
                    },
                    "15m": {
                        "windowSeconds": 900,
                        "shareCount": 5,
                        "acceptedShares": 4,
                        "rejectedShares": 1,
                        "hashrate": 19088743.537777778
                    }
                }
            },
            "workers": [
                {
                    "name": "rig01",
                    "hashrate": 42949672.96,
                    "lastShareAt": "2999-01-01T00:00:00Z",
                    "acceptedShares": 3,
                    "rejectedShares": 1,
                    "shareCount": 4,
                    "rolling": {
                        "1m": {
                            "windowSeconds": 60,
                            "shareCount": 1,
                            "acceptedShares": 1,
                            "rejectedShares": 0,
                            "hashrate": 71582788.26666667
                        },
                        "5m": {
                            "windowSeconds": 300,
                            "shareCount": 4,
                            "acceptedShares": 3,
                            "rejectedShares": 1,
                            "hashrate": 42949672.96
                        },
                        "15m": {
                            "windowSeconds": 900,
                            "shareCount": 4,
                            "acceptedShares": 3,
                            "rejectedShares": 1,
                            "hashrate": 14316557.653333334
                        }
                    }
                },
                {
                    "name": "rig02",
                    "hashrate": 14316557.653333334,
                    "lastShareAt": "2999-01-01T00:00:00Z",
                    "acceptedShares": 1,
                    "rejectedShares": 0,
                    "shareCount": 1,
                    "rolling": {
                        "1m": {
                            "windowSeconds": 60,
                            "shareCount": 0,
                            "acceptedShares": 0,
                            "rejectedShares": 0,
                            "hashrate": None
                        },
                        "5m": {
                            "windowSeconds": 300,
                            "shareCount": 1,
                            "acceptedShares": 1,
                            "rejectedShares": 0,
                            "hashrate": 14316557.653333334
                        },
                        "15m": {
                            "windowSeconds": 900,
                            "shareCount": 1,
                            "acceptedShares": 1,
                            "rejectedShares": 0,
                            "hashrate": 4772185.884444445
                        }
                    }
                }
            ],
            "payments": []
        }
    }
    runtime_snapshot["meta"]["placeholderFields"] = [
        "pool.lastBlockFoundAt",
        "network.reward",
        "blocks.reward",
        "payments"
    ]
    return runtime_snapshot


def make_activity_snapshot() -> dict:
    runtime_snapshot = make_runtime_snapshot()
    return {
        "generatedAt": "2999-01-01T00:00:01Z",
        "meta": {
            "schemaVersion": "1.0",
            "activityMode": "stratum-share-ingest",
            "activityDataSource": "stratum-jsonl-share-log",
            "activityDerivedFromShares": True,
            "blockchainVerified": False,
            "syntheticJobMode": "synthetic-stratum-v1",
            "shareValidationMode": "structural-skeleton",
            "hashratePolicy": "share-rate-assumed-diff",
            "assumedShareDifficulty": 1.0,
            "submitValidationMode": "structural-skeleton",
            "submitHashValidCount": 5,
            "submitHashInvalidCount": 2,
            "submitDuplicateWindowSize": 512,
            "submitCandidatePossibleCount": 3,
            "shareHashValidationMode": "hoohashv110-pepew-header80",
            "submitClassificationCounts": {
                "current": 4,
                "previous": 1,
                "stale": 1,
                "unknown": 0,
                "malformed": 1
            },
            "submitRejectReasonCounts": {
                "stale-job": 1,
                "malformed-submit": 1
            },
            "submitTargetValidationCounts": {
                "candidate-possible": 3,
                "target-context-missing": 0,
                "target-context-mismatch": 1
            },
            "submitShareHashValidationCounts": {
                "share-hash-valid": 2,
                "share-hash-invalid": 1,
                "preimage-missing": 0,
                "preimage-mismatch": 1
            },
            "windowSeconds": [60, 300, 900],
            "lastShareAt": "2999-01-01T00:00:00Z",
            "warningCount": 0,
            "sequence": 5,
            "logPath": "/var/lib/pepepow-pool/share-events.jsonl",
            "logOffset": 100,
            "logInode": 1234,
            "windowReplayOffset": 0,
            "windowReplaySequenceFloor": 1,
            "dataStatus": "live",
            "templateModeConfigured": "daemon-template",
            "templateModeEffective": "daemon-template",
            "templateDaemonRpcStatus": "reachable",
            "templateDaemonRpcReachable": True,
            "templateFetchStatus": "ok",
            "templateLastAttemptAt": "2999-01-01T00:00:01Z",
            "templateLastSuccessAt": "2999-01-01T00:00:01Z",
            "templateLatestTemplateAgeSeconds": 0,
            "templateLatestTemplateAnchor": "deadbeefcafebabe00112233",
            "templateLastError": None,
            "activeJobCount": 1
        },
        "pool": {
            "poolHashrate": 57266230.61333334,
            "activeMiners": 2,
            "activeWorkers": 3,
            "workerDistribution": [
                {
                    "wallet": "PEPEPOW1KnownWalletAddress000000",
                    "workers": 2,
                    "activeWorkers": 2,
                    "shares15m": 5,
                    "hashrate": 57266230.61333334
                }
            ],
            "rolling": runtime_snapshot["miners"]["PEPEPOW1KnownWalletAddress000000"]["summary"]["rolling"]
        },
        "miners": runtime_snapshot["miners"],
        "jobs": {
            "configuredMode": "daemon-template",
            "currentMode": "daemon-template",
            "daemonRpcStatus": "reachable",
            "daemonRpcReachable": True,
            "templateFetchStatus": "ok",
            "lastAttemptAt": "2999-01-01T00:00:01Z",
            "lastSuccessAt": "2999-01-01T00:00:01Z",
            "latestTemplateAgeSeconds": 0,
            "latestTemplateAnchor": "deadbeefcafebabe00112233",
            "lastError": None,
            "activeJobCount": 1,
            "active": [
                {
                    "jobId": "job-0000000000000001",
                    "templateAnchor": "deadbeefcafebabe00112233",
                    "targetContext": {
                        "bits": "1c0ffff0",
                        "target": "0f" * 32,
                        "height": 123456,
                        "version": "20000000",
                        "curtime": 1713225600
                    },
                    "createdAt": "2999-01-01T00:00:01Z",
                    "expiresAt": "2999-01-01T00:03:01Z",
                    "staleBasis": "created+180s",
                    "stale": False,
                    "ageSeconds": 0,
                    "source": "daemon-template"
                }
            ]
        }
    }


def make_config(
    runtime_snapshot_path: Path,
    fallback_snapshot_path: Path,
    activity_snapshot_path: Path | None = None,
) -> AppConfig:
    return AppConfig(
        app_name="test-api",
        version="test",
        host="127.0.0.1",
        port=8080,
        runtime_snapshot_path=runtime_snapshot_path,
        fallback_snapshot_path=fallback_snapshot_path,
        activity_snapshot_path=activity_snapshot_path
        or Path("/tmp/pepepow-activity-snapshot.json"),
        cache_ttl_seconds=1,
        stale_after_seconds=180,
        allowed_wallet_pattern=r"^[A-Za-z0-9]{26,128}$",
    )


class ApiEndpointTests(unittest.TestCase):
    def test_health_endpoint_prefers_runtime_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "runtime.json"
            runtime_payload = make_runtime_snapshot()
            runtime_payload["generatedAt"] = "2999-01-01T00:00:00Z"
            runtime_path.write_text(
                json.dumps(runtime_payload), encoding="utf-8"
            )

            app = create_app(make_config(runtime_path, FALLBACK_SNAPSHOT_PATH))
            client = app.test_client()

            response = client.get("/api/health")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["service"], "test-api")
            self.assertEqual(
                payload["localServiceBaseline"],
                {
                    "core": True,
                    "api": True,
                    "stratum": True,
                    "frontendExpected": False,
                    "deploymentVariant": "core-api-stratum-no-local-frontend",
                },
            )
            self.assertEqual(payload["snapshotSource"], "runtime")
            self.assertFalse(payload["degraded"])
            self.assertFalse(payload["stale"])
            self.assertEqual(payload["chainState"], "reindexing")
            self.assertEqual(payload["activityDataStatus"], "live")

    def test_pool_summary_includes_data_status(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "runtime.json"
            runtime_payload = make_runtime_snapshot()
            runtime_payload["generatedAt"] = "2999-01-01T00:00:00Z"
            runtime_path.write_text(
                json.dumps(runtime_payload), encoding="utf-8"
            )

            app = create_app(make_config(runtime_path, FALLBACK_SNAPSHOT_PATH))
            client = app.test_client()

            response = client.get("/api/pool/summary")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["coin"], "PEPEPOW")
            self.assertEqual(payload["algorithm"], "hoohashv110-pepew")
            self.assertEqual(payload["dataStatus"], "live")
            self.assertEqual(payload["activeMiners"], 2)
            self.assertEqual(payload["activityMode"], "testing-local-ingest")
            self.assertNotIn("pool.poolHashrate", payload["placeholderFields"])
            self.assertNotIn("pool.activeMiners", payload["placeholderFields"])
            self.assertEqual(payload["hashratePolicy"], "share-rate-assumed-diff")

    def test_hashrate_history_endpoint_returns_rolling_snapshot_samples(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "runtime.json"
            runtime_payload = make_runtime_snapshot()
            runtime_payload["generatedAt"] = "2999-01-01T00:00:00Z"
            runtime_payload["network"]["networkHashrate"] = 987654321.0
            runtime_path.write_text(
                json.dumps(runtime_payload), encoding="utf-8"
            )

            app = create_app(make_config(runtime_path, FALLBACK_SNAPSHOT_PATH))
            client = app.test_client()

            response = client.get("/api/hashrate/history")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["maxAgeSeconds"], 24 * 60 * 60)
            self.assertEqual(payload["maxPoints"], 1440)
            self.assertEqual(len(payload["pool"]), 1)
            self.assertEqual(len(payload["network"]), 1)
            self.assertEqual(payload["pool"][0]["h"], 57266230.61333334)
            self.assertEqual(payload["network"][0]["h"], 987654321.0)

    def test_blocks_endpoint_uses_runtime_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "runtime.json"
            runtime_payload = make_runtime_snapshot()
            runtime_payload["generatedAt"] = "2999-01-01T00:00:00Z"
            runtime_path.write_text(
                json.dumps(runtime_payload), encoding="utf-8"
            )
            candidates_path = Path(tmp_dir) / "accepted-candidates.json"
            candidates_path.write_text(
                json.dumps({
                    "accepted_candidates": [
                        {
                            "candidate_hash": "candidate-block-hash",
                            "submit_timestamp": "2026-06-05T12:42:37Z",
                            "matched_height": 4573284,
                            "matched_block_hash": "matched-block-hash",
                            "lifecycle_status": "chain_match_found",
                            "confirmations": 5,
                            "maturity_label": "immature",
                            "difficulty": "123.45",
                        }
                    ]
                }),
                encoding="utf-8",
            )

            app = create_app(make_config(runtime_path, FALLBACK_SNAPSHOT_PATH))
            client = app.test_client()

            response = client.get("/api/blocks")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["kind"], "observed-network-blocks")
            self.assertEqual(payload["dataStatus"], "live")
            self.assertIsInstance(payload["items"], list)
            self.assertGreaterEqual(len(payload["items"]), 1)
            self.assertIn("blocks", payload)
            first_block = payload["blocks"][0]
            self.assertEqual(first_block["coin"], "PEPEW")
            self.assertEqual(first_block["time"], "1780663357")
            self.assertEqual(first_block["height"], "4573284")
            self.assertEqual(first_block["category"], "immature")
            self.assertEqual(first_block["difficulty"], "123.45")
            self.assertEqual(first_block["difficulty_user"], "123.45")

    def test_accepted_candidates_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "pool-snapshot.json"
            runtime_payload = make_runtime_snapshot()
            runtime_path.write_text(
                json.dumps(runtime_payload), encoding="utf-8"
            )

            candidates_path = Path(tmp_dir) / "accepted-candidates.json"
            candidates_payload = {
                "updated_at": "2026-06-05T15:40:12Z",
                "accepted_candidates": [
                    {
                        "candidate_hash": "hash-abc",
                        "job_id": "job-123",
                        "submit_timestamp": "2026-06-05T12:42:37Z",
                        "daemon_result": None,
                        "followup_status": "match-found",
                        "matched_height": 4573284,
                        "matched_block_hash": "hash-abc",
                        "lifecycle_status": "chain_match_found",
                        "confirmations": 5,
                        "maturity_label": "immature",
                    }
                ]
            }
            candidates_path.write_text(
                json.dumps(candidates_payload), encoding="utf-8"
            )

            app = create_app(make_config(runtime_path, FALLBACK_SNAPSHOT_PATH))
            client = app.test_client()

            response = client.get("/api/accepted-candidates")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            items = payload["items"]
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["candidateHash"], "hash-abc")
            self.assertEqual(items[0]["jobId"], "job-123")
            self.assertEqual(items[0]["submitTimestamp"], "2026-06-05T12:42:37Z")
            self.assertIsNone(items[0]["submitblockDaemonResult"])
            self.assertEqual(items[0]["followupStatus"], "match-found")
            self.assertEqual(items[0]["matchedHeight"], 4573284)
            self.assertEqual(items[0]["matchedBlockHash"], "hash-abc")
            self.assertEqual(items[0]["lifecycleStatus"], "chain_match_found")
            self.assertEqual(items[0]["confirmations"], 5)
            self.assertEqual(items[0]["maturityLabel"], "immature")

    def test_accepted_candidates_endpoint_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "pool-snapshot.json"
            runtime_payload = make_runtime_snapshot()
            runtime_path.write_text(
                json.dumps(runtime_payload), encoding="utf-8"
            )

            app = create_app(make_config(runtime_path, FALLBACK_SNAPSHOT_PATH))
            client = app.test_client()

            response = client.get("/api/accepted-candidates")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["items"], [])

    def test_payments_endpoint_is_placeholder(self):
        app = create_app(
            make_config(Path("/tmp/does-not-exist.json"), FALLBACK_SNAPSHOT_PATH)
        )
        client = app.test_client()
        response = client.get("/api/payments")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["items"], [])

    def test_operator_status_endpoint_sanitizes_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "pool-snapshot.json"
            runtime_payload = make_runtime_snapshot()
            runtime_path.write_text(json.dumps(runtime_payload), encoding="utf-8")
            operator_path = Path(tmp_dir) / "operator-status.json"
            operator_path.write_text(
                json.dumps(
                    {
                        "generatedAt": "2999-01-01T00:00:00Z",
                        "status": "ok",
                        "runtimeDir": "/var/lib/secret",
                        "items": [
                            {
                                "key": "pool_health",
                                "label": "Bad Label",
                                "status": "ok",
                                "message": "Snapshots fresh",
                                "path": "/var/lib/secret/pool-snapshot.json",
                            },
                            {
                                "key": "wallet_watchdog",
                                "label": "Wallet Watchdog",
                                "status": "warning",
                                "message": "Review wallet growth",
                                "errors": ["internal detail"],
                            },
                            {
                                "key": "payment_audit",
                                "label": "Payment Audit",
                                "status": "error",
                                "message": "Payment records need review",
                                "issues": [{"txid": "secret"}],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            app = create_app(
                make_config(
                    runtime_path,
                    FALLBACK_SNAPSHOT_PATH,
                    activity_snapshot_path=Path(tmp_dir) / "activity-snapshot.json",
                )
            )
            client = app.test_client()
            response = client.get("/api/operator-status")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()

        self.assertEqual(payload["generatedAt"], "2999-01-01T00:00:00Z")
        self.assertEqual(payload["status"], "ok")
        self.assertEqual([item["label"] for item in payload["items"]], ["Pool Health", "Wallet Watchdog", "Payment Audit"])
        self.assertEqual(payload["items"][0]["message"], "Snapshots fresh")
        for item in payload["items"]:
            self.assertEqual(set(item), {"key", "label", "status", "message"})
        self.assertNotIn("runtimeDir", payload)

    def test_operator_status_endpoint_missing_snapshot_returns_unknown(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = create_app(
                make_config(
                    Path(tmp_dir) / "does-not-exist.json",
                    FALLBACK_SNAPSHOT_PATH,
                    activity_snapshot_path=Path(tmp_dir) / "activity-snapshot.json",
                )
            )
            client = app.test_client()
            response = client.get("/api/operator-status")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
        self.assertEqual(payload["status"], "unknown")
        self.assertEqual(len(payload["items"]), 3)
        self.assertEqual({item["status"] for item in payload["items"]}, {"unknown"})

    def test_miner_endpoint_returns_wallet_summary_and_workers(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "runtime.json"
            runtime_payload = make_runtime_snapshot()
            runtime_payload["generatedAt"] = "2999-01-01T00:00:00Z"
            runtime_path.write_text(
                json.dumps(runtime_payload), encoding="utf-8"
            )

            app = create_app(make_config(runtime_path, FALLBACK_SNAPSHOT_PATH))
            client = app.test_client()
            response = client.get("/api/miner/PEPEPOW1KnownWalletAddress000000")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["found"])
            self.assertTrue(payload["implemented"])
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["summary"]["acceptedShares"], 4)
            self.assertEqual(len(payload["workers"]), 2)

    def test_miner_endpoint_returns_not_found_when_wallet_missing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "runtime.json"
            runtime_payload = make_runtime_snapshot()
            runtime_payload["generatedAt"] = "2999-01-01T00:00:00Z"
            runtime_path.write_text(
                json.dumps(runtime_payload), encoding="utf-8"
            )

            app = create_app(make_config(runtime_path, FALLBACK_SNAPSHOT_PATH))
            client = app.test_client()
            response = client.get("/api/miner/PEPEPOW1UnknownWalletAddress000000")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertFalse(payload["found"])
            self.assertTrue(payload["implemented"])
            self.assertEqual(payload["status"], "ok")

    def test_invalid_wallet_rejected(self):
        app = create_app(
            make_config(Path("/tmp/does-not-exist.json"), FALLBACK_SNAPSHOT_PATH)
        )
        client = app.test_client()
        response = client.get("/api/miner/not-valid!!!")
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertIn("invalid", payload["error"]["message"].lower())

    def test_missing_runtime_uses_fallback(self):
        app = create_app(
            make_config(Path("/tmp/does-not-exist.json"), FALLBACK_SNAPSHOT_PATH)
        )
        client = app.test_client()
        response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["snapshotSource"], "fallback")
        self.assertTrue(payload["degraded"])
        self.assertIn("Runtime snapshot", payload["lastError"])

    def test_stale_runtime_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "runtime.json"
            runtime_payload = load_snapshot(FALLBACK_SNAPSHOT_PATH)
            runtime_payload["meta"]["degraded"] = False
            runtime_payload["generatedAt"] = "2020-01-01T00:00:00Z"
            runtime_path.write_text(
                json.dumps(runtime_payload), encoding="utf-8"
            )

            app = create_app(make_config(runtime_path, FALLBACK_SNAPSHOT_PATH))
            client = app.test_client()

            response = client.get("/api/health")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["snapshotSource"], "runtime")
            self.assertTrue(payload["degraded"])
            self.assertTrue(payload["stale"])

    def test_health_includes_activity_metadata(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "runtime.json"
            runtime_payload = make_runtime_snapshot()
            runtime_payload["generatedAt"] = "2999-01-01T00:00:00Z"
            runtime_path.write_text(
                json.dumps(runtime_payload), encoding="utf-8"
            )

            app = create_app(make_config(runtime_path, FALLBACK_SNAPSHOT_PATH))
            client = app.test_client()
            response = client.get("/api/health")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["activityMode"], "testing-local-ingest")
            self.assertEqual(payload["activityDataSource"], "local-jsonl-share-log")
            self.assertEqual(payload["activityWindowSeconds"], 900)
            self.assertEqual(payload["hashratePolicy"], "share-rate-assumed-diff")

    def test_activity_snapshot_overlays_fallback_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            activity_path = Path(tmp_dir) / "activity.json"
            activity_path.write_text(
                json.dumps(make_activity_snapshot()), encoding="utf-8"
            )

            app = create_app(
                make_config(
                    Path("/tmp/does-not-exist-runtime.json"),
                    FALLBACK_SNAPSHOT_PATH,
                    activity_snapshot_path=activity_path,
                )
            )
            client = app.test_client()

            response = client.get("/api/pool/summary")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["dataStatus"], "fallback")
            self.assertEqual(payload["activeMiners"], 2)
            self.assertEqual(payload["poolHashrate"], 57266230.61333334)
            self.assertEqual(payload["activityMode"], "stratum-share-ingest")
            self.assertTrue(payload["activityDerivedFromShares"])
            self.assertEqual(payload["templateModeEffective"], "daemon-template")
            self.assertEqual(payload["activeJobCount"], 1)

            miner_response = client.get("/api/miner/PEPEPOW1KnownWalletAddress000000")
            self.assertEqual(miner_response.status_code, 200)
            miner_payload = miner_response.get_json()
            self.assertTrue(miner_payload["found"])
            self.assertEqual(miner_payload["summary"]["shareCount"], 5)

            health_response = client.get("/api/health")
            self.assertEqual(health_response.status_code, 200)
            health_payload = health_response.get_json()
            self.assertEqual(health_payload["templateModeEffective"], "daemon-template")
            self.assertEqual(health_payload["templateDaemonRpcStatus"], "reachable")
            self.assertEqual(health_payload["templateFetchStatus"], "ok")
            self.assertEqual(health_payload["activeJobCount"], 1)
            self.assertEqual(
                health_payload["submitValidationMode"], "structural-skeleton"
            )
            self.assertEqual(health_payload["submitHashValidCount"], 5)
            self.assertEqual(health_payload["submitHashInvalidCount"], 2)
            self.assertEqual(health_payload["submitCandidatePossibleCount"], 3)
            self.assertEqual(
                health_payload["shareHashValidationMode"],
                "hoohashv110-pepew-header80",
            )
            self.assertEqual(
                health_payload["submitRejectReasonCounts"]["stale-job"], 1
            )
            self.assertEqual(
                health_payload["submitTargetValidationCounts"][
                    "target-context-mismatch"
                ],
                1,
            )
            self.assertEqual(
                health_payload["submitShareHashValidationCounts"][
                    "share-hash-valid"
                ],
                2,
            )
            self.assertEqual(
                health_payload["submitShareHashValidationCounts"][
                    "preimage-mismatch"
                ],
                1,
            )

    def test_missing_all_snapshots_returns_503(self):
        missing_path = REPO_ROOT / "apps" / "api" / "data" / "mock" / "missing.json"
        app = create_app(make_config(missing_path, missing_path))
        client = app.test_client()
        response = client.get("/api/health")
        self.assertEqual(response.status_code, 503)

    def test_invalid_runtime_falls_back_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "runtime.json"
            runtime_path.write_text("{not-json", encoding="utf-8")
            app = create_app(make_config(runtime_path, FALLBACK_SNAPSHOT_PATH))
            client = app.test_client()
            response = client.get("/api/network/summary")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["dataStatus"], "fallback")

    def test_rounds_endpoint_valid_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "pool-snapshot.json"
            runtime_payload = make_runtime_snapshot()
            runtime_path.write_text(
                json.dumps(runtime_payload), encoding="utf-8"
            )

            rounds_path = Path(tmp_dir) / "rounds-snapshot.json"
            rounds_payload = {
                "updated_at": "2026-06-05T15:40:12Z",
                "rounds": [
                    {
                        "round_id": "round-hash-123",
                        "candidate_hash": "round-hash-123",
                        "height": 100,
                        "status": "confirmed",
                        "submit_timestamp": "2026-06-05T12:00:00Z",
                        "confirmations": 105,
                        "shares": {
                            "walletA": {
                                "share_count": 10,
                                "share_score": 10.0,
                                "share_percent": 66.666667,
                                "workers": {
                                    "rig01": {
                                        "share_count": 10,
                                        "share_score": 10.0,
                                        "share_percent": 66.666667,
                                        "wallet_share_percent": 100.0,
                                    }
                                }
                            },
                            "walletB": {
                                "share_count": 5,
                                "share_score": 5.0,
                                "share_percent": 33.333333,
                            }
                        },
                        "total_share_count": 15,
                        "total_share_score": 15.0,
                        "wallet_count": 2,
                        "worker_count": 1
                    }
                ]
            }
            rounds_path.write_text(
                json.dumps(rounds_payload), encoding="utf-8"
            )

            config = make_config(
                runtime_path,
                FALLBACK_SNAPSHOT_PATH,
                activity_snapshot_path=Path(tmp_dir) / "rounds-snapshot.json"
            )
            app = create_app(config)
            client = app.test_client()

            response = client.get("/api/rounds")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            items = payload["items"]
            self.assertEqual(len(items), 1)
            r = items[0]
            self.assertEqual(r["roundId"], "round-hash-123")
            self.assertEqual(r["candidateHash"], "round-hash-123")
            self.assertEqual(r["height"], 100)
            self.assertEqual(r["matchedHeight"], 100)
            self.assertEqual(r["status"], "confirmed")
            self.assertEqual(r["roundStatus"], "confirmed")
            self.assertEqual(r["lifecycleStatus"], "confirmed")
            self.assertEqual(r["submitTimestamp"], "2026-06-05T12:00:00Z")
            self.assertEqual(r["confirmations"], 105)
            self.assertEqual(r["totalShareCount"], 15)
            self.assertEqual(r["totalShareScore"], 15.0)
            self.assertEqual(r["walletCount"], 2)
            self.assertEqual(r["workerCount"], 1)
            self.assertEqual(r["shares"]["walletA"]["shareCount"], 10)
            self.assertEqual(r["shares"]["walletA"]["shareScore"], 10.0)
            self.assertAlmostEqual(r["shares"]["walletA"]["sharePercent"], 66.666667, places=4)
            self.assertEqual(r["shares"]["walletA"]["workers"]["rig01"]["shareCount"], 10)
            self.assertEqual(r["shares"]["walletA"]["workers"]["rig01"]["shareScore"], 10.0)
            self.assertAlmostEqual(r["shares"]["walletA"]["workers"]["rig01"]["sharePercent"], 66.666667, places=4)
            self.assertAlmostEqual(r["shares"]["walletA"]["workers"]["rig01"]["walletSharePercent"], 100.0, places=4)
            self.assertEqual(r["shares"]["walletB"]["shareCount"], 5)
            self.assertEqual(r["shares"]["walletB"]["shareScore"], 5.0)
            self.assertAlmostEqual(r["shares"]["walletB"]["sharePercent"], 33.333333, places=4)

    def test_rounds_endpoint_missing_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "pool-snapshot.json"
            runtime_payload = make_runtime_snapshot()
            runtime_path.write_text(
                json.dumps(runtime_payload), encoding="utf-8"
            )

            config = make_config(
                runtime_path,
                FALLBACK_SNAPSHOT_PATH,
                activity_snapshot_path=Path(tmp_dir) / "does-not-exist.json"
            )
            app = create_app(config)
            client = app.test_client()

            response = client.get("/api/rounds")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["items"], [])

    def test_rounds_endpoint_malformed_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "pool-snapshot.json"
            runtime_payload = make_runtime_snapshot()
            runtime_path.write_text(
                json.dumps(runtime_payload), encoding="utf-8"
            )

            rounds_path = Path(tmp_dir) / "rounds-snapshot.json"
            rounds_path.write_text("{malformed-json", encoding="utf-8")

            config = make_config(
                runtime_path,
                FALLBACK_SNAPSHOT_PATH,
                activity_snapshot_path=rounds_path
            )
            app = create_app(config)
            client = app.test_client()

            response = client.get("/api/rounds")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["items"], [])

    def test_payments_endpoint_returns_enriched_fields(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "pool-snapshot.json"
            runtime_payload = make_runtime_snapshot()
            runtime_path.write_text(
                json.dumps(runtime_payload), encoding="utf-8"
            )

            payments_path = Path(tmp_dir) / "payments-snapshot.json"
            payments_payload = {
                "updated_at": "2026-06-06T15:00:00Z",
                "items": [
                    {
                        "wallet": "PL8s5WjXUGhHVSo743dwEXGtsifV5YpdcD",
                        "amount": 6930.0,
                        "paidAt": "2026-06-06T15:41:59.648957Z",
                        "confirmations": 1,
                        "txid": "c7b439336d9d326610a09404efb8de4104a1532d7d8ac46629bf61e89b56540e",
                        "candidateHash": "000000158d4880a187ec04e02c96af5e977ca3c552e5f2e0a9536ec5411c99a2",
                        "blockHash": "000000158d4880a187ec04e02c96af5e977ca3c552e5f2e0a9536ec5411c99a2",
                        "blockHeight": 4573193,
                        "status": "ready_for_manual_review"
                    }
                ]
            }
            payments_path.write_text(
                json.dumps(payments_payload), encoding="utf-8"
            )

            config = make_config(
                runtime_path,
                FALLBACK_SNAPSHOT_PATH,
                activity_snapshot_path=payments_path
            )
            app = create_app(config)
            client = app.test_client()

            response = client.get("/api/payments")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            items = payload["items"]
            self.assertEqual(len(items), 1)
            item = items[0]
            self.assertEqual(item["wallet"], "PL8s5WjXUGhHVSo743dwEXGtsifV5YpdcD")
            self.assertEqual(item["amount"], 6930.0)
            self.assertEqual(item["candidateHash"], "000000158d4880a187ec04e02c96af5e977ca3c552e5f2e0a9536ec5411c99a2")
            self.assertEqual(item["blockHeight"], 4573193)
            self.assertEqual(item["status"], "ready_for_manual_review")

    def test_payments_endpoint_malformed_snapshot_fallback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "pool-snapshot.json"
            runtime_payload = make_runtime_snapshot()
            runtime_path.write_text(
                json.dumps(runtime_payload), encoding="utf-8"
            )

            payments_path = Path(tmp_dir) / "payments-snapshot.json"
            payments_path.write_text("{malformed-json", encoding="utf-8")

            config = make_config(
                runtime_path,
                FALLBACK_SNAPSHOT_PATH,
                activity_snapshot_path=payments_path
            )
            app = create_app(config)
            client = app.test_client()

            response = client.get("/api/payments")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["items"], [])

    def test_miner_endpoint_includes_manual_payments(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "pool-snapshot.json"
            runtime_payload = make_runtime_snapshot()
            runtime_path.write_text(
                json.dumps(runtime_payload), encoding="utf-8"
            )

            payments_path = Path(tmp_dir) / "payments-snapshot.json"
            payments_payload = {
                "items": [
                    {
                        "wallet": "PEPEPOW1KnownWalletAddress000000",
                        "amount": 1200.0,
                        "confirmations": 10,
                        "txid": "txid_match_1",
                        "timestamp": "2026-06-13T06:00:00Z",
                        "blockHeight": 4500000,
                        "blockHash": "block_hash_1",
                        "status": "ready_for_manual_review"
                    },
                    {
                        "wallet": "PEPEPOW1KnownWalletAddress000000",
                        "amount": 800.5,
                        "confirmations": 5,
                        "txid": "txid_match_2",
                        "paidAt": "2026-06-13T07:00:00Z",
                        "candidate_id": "candidate_hash_match_2",
                        "blockHeight": 4500100,
                        "note": "manual backfill",
                        "status": "ready_for_manual_review"
                    },
                    {
                        "wallet": "PEPEPOW1OtherWalletAddress999999",
                        "amount": 500.0,
                        "confirmations": 20,
                        "txid": "txid_other",
                        "blockHeight": 4500200,
                        "status": "ready_for_manual_review"
                    }
                ]
            }
            payments_path.write_text(
                json.dumps(payments_payload), encoding="utf-8"
            )

            config = make_config(
                runtime_path,
                FALLBACK_SNAPSHOT_PATH,
                activity_snapshot_path=payments_path
            )
            app = create_app(config)
            client = app.test_client()

            response = client.get("/api/miner/PEPEPOW1KnownWalletAddress000000")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            
            self.assertIn("recentPayments", payload)
            self.assertIn("totalPaidManual", payload)
            self.assertEqual(len(payload["recentPayments"]), 2)
            self.assertEqual(payload["recentPayments"][0]["txid"], "txid_match_2")
            self.assertEqual(payload["recentPayments"][0]["candidateId"], "candidate_hash_match_2")
            self.assertEqual(payload["recentPayments"][0]["timestamp"], "2026-06-13T07:00:00Z")
            self.assertEqual(payload["recentPayments"][1]["txid"], "txid_match_1")
            self.assertEqual(payload["recentPayments"][1]["paidAt"], "2026-06-13T06:00:00Z")
            self.assertEqual(payload["recentPayments"][1]["timestamp"], "2026-06-13T06:00:00Z")
            self.assertAlmostEqual(payload["totalPaidManual"], 2000.5)

    def test_miner_endpoint_limits_recent_payments_after_sorting(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "pool-snapshot.json"
            runtime_payload = make_runtime_snapshot()
            runtime_path.write_text(
                json.dumps(runtime_payload), encoding="utf-8"
            )

            payments_path = Path(tmp_dir) / "payments-snapshot.json"
            payments_payload = {
                "items": [
                    {
                        "wallet": "PEPEPOW1KnownWalletAddress000000",
                        "amount": 1.0,
                        "txid": f"txid_match_{i:02d}",
                        "timestamp": f"2026-06-13T00:{i:02d}:00Z",
                    }
                    for i in range(55)
                ]
            }
            payments_path.write_text(
                json.dumps(payments_payload), encoding="utf-8"
            )

            config = make_config(
                runtime_path,
                FALLBACK_SNAPSHOT_PATH,
                activity_snapshot_path=payments_path
            )
            app = create_app(config)
            client = app.test_client()

            response = client.get("/api/miner/PEPEPOW1KnownWalletAddress000000")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()

            self.assertEqual(len(payload["recentPayments"]), 50)
            self.assertEqual(payload["recentPayments"][0]["txid"], "txid_match_54")
            self.assertEqual(payload["recentPayments"][-1]["txid"], "txid_match_05")
            self.assertAlmostEqual(payload["totalPaidManual"], 55.0)

    def test_miner_endpoint_payments_fallback_safe(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "pool-snapshot.json"
            runtime_payload = make_runtime_snapshot()
            runtime_path.write_text(
                json.dumps(runtime_payload), encoding="utf-8"
            )

            payments_path = Path(tmp_dir) / "payments-snapshot.json"
            payments_path.write_text("{malformed-json", encoding="utf-8")

            config = make_config(
                runtime_path,
                FALLBACK_SNAPSHOT_PATH,
                activity_snapshot_path=payments_path
            )
            app = create_app(config)
            client = app.test_client()

            response = client.get("/api/miner/PEPEPOW1KnownWalletAddress000000")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            
            self.assertEqual(payload["recentPayments"], [])
            self.assertEqual(payload["totalPaidManual"], 0.0)

    def test_stats_endpoint_returns_compatibility_shape(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "pool-snapshot.json"
            runtime_payload = make_runtime_snapshot()
            runtime_path.write_text(
                json.dumps(runtime_payload), encoding="utf-8"
            )

            candidates_path = Path(tmp_dir) / "accepted-candidates.json"
            candidates_path.write_text(
                json.dumps({
                    "accepted_candidates": [
                        {"lifecycle_status": "confirmed"},
                        {"lifecycle_status": "immature"},
                        {"lifecycle_status": "orphan"},
                    ]
                }),
                encoding="utf-8",
            )
            payments_path = Path(tmp_dir) / "payments-snapshot.json"
            payments_path.write_text(
                json.dumps({"items": [{"amount": 100.5}, {"amount": 9.5}]}),
                encoding="utf-8",
            )

            app = create_app(make_config(runtime_path, FALLBACK_SNAPSHOT_PATH))
            client = app.test_client()

            response = client.get("/api/stats")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertIn("global", payload)
            self.assertIn("hoohashv110", payload["algos"])
            self.assertIn("hoohashv110-pepew", payload["pools"])
            pool = payload["pools"]["hoohashv110-pepew"]
            self.assertEqual(pool["symbol"], "PEPEW")
            self.assertEqual(pool["algorithm"], "hoohashv110")
            self.assertEqual(pool["workerCount"], 3)
            self.assertEqual(pool["blocks"]["confirmed"], 1)
            self.assertEqual(pool["blocks"]["pending"], 1)
            self.assertEqual(pool["blocks"]["orphaned"], 1)
            self.assertEqual(pool["poolStats"]["validShares"], "4")
            self.assertEqual(pool["poolStats"]["invalidShares"], "1")
            self.assertEqual(pool["poolStats"]["totalPaid"], "110.0")

    def test_status_endpoint_returns_compatibility_shape(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "pool-snapshot.json"
            runtime_payload = make_runtime_snapshot()
            runtime_path.write_text(
                json.dumps(runtime_payload), encoding="utf-8"
            )
            candidates_path = Path(tmp_dir) / "accepted-candidates.json"
            candidates_path.write_text(
                json.dumps({
                    "accepted_candidates": [
                        {
                            "submit_timestamp": "2026-06-05T12:42:37Z",
                            "matched_height": 4573284,
                            "matched_block_hash": "hash-abc",
                            "lifecycle_status": "confirmed",
                        }
                    ]
                }),
                encoding="utf-8",
            )

            app = create_app(make_config(runtime_path, FALLBACK_SNAPSHOT_PATH))
            client = app.test_client()

            response = client.get("/api/status")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertIn("hoohashv110", payload)
            algo = payload["hoohashv110"]
            self.assertEqual(algo["name"], "hoohashv110")
            self.assertEqual(algo["port"], 39333)
            self.assertEqual(algo["coins"], 1)
            self.assertEqual(algo["fees"], 1)
            self.assertEqual(algo["workers"], 3)
            self.assertEqual(algo["hashrate"], 57266230.61333334)
            self.assertEqual(algo["hashrate_last24h"], 57266230.61333334)
            self.assertEqual(algo["lastblock"], 4573284)
            self.assertIn("timesincelast", algo)
            self.assertNotIn("estimate_current", algo)
            self.assertNotIn("actual_last24h", algo)
            self.assertNotIn("rental_current", algo)
            self.assertNotIn("24h_btc", algo)

    def test_stats_and_status_missing_snapshots_do_not_500(self):
        missing_path = REPO_ROOT / "apps" / "api" / "data" / "mock" / "missing.json"
        app = create_app(make_config(missing_path, missing_path))
        client = app.test_client()

        stats_response = client.get("/api/stats")
        self.assertEqual(stats_response.status_code, 200)
        stats_payload = stats_response.get_json()
        self.assertEqual(stats_payload["global"]["workers"], 0)
        self.assertEqual(stats_payload["global"]["hashrate"], 0.0)
        self.assertIn("hoohashv110-pepew", stats_payload["pools"])

        status_response = client.get("/api/status")
        self.assertEqual(status_response.status_code, 200)
        status_payload = status_response.get_json()
        self.assertIn("hoohashv110", status_payload)
        self.assertEqual(status_payload["hoohashv110"]["workers"], 0)
        self.assertEqual(status_payload["hoohashv110"]["hashrate"], 0.0)

    def test_price_endpoint_success(self):
        from unittest.mock import patch, MagicMock

        app = create_app(make_config(FALLBACK_SNAPSHOT_PATH, FALLBACK_SNAPSHOT_PATH))
        client = app.test_client()

        mock_response = MagicMock()
        mock_response.read.return_value = b'{"ticker_id":"PEPEW_USDT","last_price":"0.000000325"}'
        mock_response.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            response = client.get("/api/price/pepew-usdt")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["symbol"], "PEPEW_USDT")
            self.assertEqual(payload["price"], 0.000000325)
            self.assertEqual(payload["source"], "nonkyc")
            self.assertIsNotNone(payload["updatedAt"])
            self.assertEqual(payload["cacheSeconds"], 120)
            mock_urlopen.assert_called_once()

    def test_price_endpoint_caching(self):
        from unittest.mock import patch, MagicMock

        app = create_app(make_config(FALLBACK_SNAPSHOT_PATH, FALLBACK_SNAPSHOT_PATH))
        client = app.test_client()

        mock_response = MagicMock()
        mock_response.read.return_value = b'{"ticker_id":"PEPEW_USDT","last_price":"0.000000325"}'
        mock_response.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            # First call triggers fetch
            response1 = client.get("/api/price/pepew-usdt")
            self.assertEqual(response1.status_code, 200)

            # Second call immediately should use cache
            response2 = client.get("/api/price/pepew-usdt")
            self.assertEqual(response2.status_code, 200)

            payload1 = response1.get_json()
            payload2 = response2.get_json()
            self.assertEqual(payload1["price"], 0.000000325)
            self.assertEqual(payload2["price"], 0.000000325)
            self.assertEqual(payload1["updatedAt"], payload2["updatedAt"])

            # Should only be called once
            mock_urlopen.assert_called_once()

    def test_price_endpoint_failure_fallback(self):
        from unittest.mock import patch, MagicMock
        import urllib.error

        app = create_app(make_config(FALLBACK_SNAPSHOT_PATH, FALLBACK_SNAPSHOT_PATH))
        client = app.test_client()

        # Case 1: Fetch fails and no price cached yet -> should return price: null
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")) as mock_urlopen:
            response = client.get("/api/price/pepew-usdt")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["price"], None)
            self.assertEqual(payload["updatedAt"], None)

        # Case 2: Seed the cache manually, then fetch fails -> should return previously cached price
        cache = app.config["PRICE_CACHE"]
        cache.price = 0.000000450
        cache.updated_at = "2026-06-12T15:00:00Z"
        # Reset last_fetch_attempt and last_fetch_success to force a new attempt
        cache.last_fetch_success = 0.0
        cache.last_fetch_attempt = 0.0

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")) as mock_urlopen:
            response = client.get("/api/price/pepew-usdt")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["price"], 0.000000450)
            self.assertEqual(payload["updatedAt"], "2026-06-12T15:00:00Z")

    def test_price_endpoint_defensive_shapes(self):
        from unittest.mock import patch, MagicMock

        app = create_app(make_config(FALLBACK_SNAPSHOT_PATH, FALLBACK_SNAPSHOT_PATH))
        client = app.test_client()

        shapes = [
            # valid last string
            (b'{"last": "0.000000330"}', 0.000000330),
            # valid price string
            (b'{"price": "0.000000340"}', 0.000000340),
            # nested ticker dict
            (b'{"ticker": {"last": "0.000000350"}}', 0.000000350),
            # nested data dict
            (b'{"data": {"last_price": "0.000000360"}}', 0.000000360),
            # list shape
            (b'[{"last": "0.000000370"}]', 0.000000370),
            # bid/ask midpoint
            (b'{"bid": "0.000000300", "ask": "0.000000400"}', 0.000000350),
            # malformed shape
            (b'{"garbage": 123}', None)
        ]

        for payload, expected_price in shapes:
            # Force cache refresh for each mock payload
            cache = app.config["PRICE_CACHE"]
            cache.price = None
            cache.last_fetch_success = 0.0
            cache.last_fetch_attempt = 0.0

            mock_response = MagicMock()
            mock_response.read.return_value = payload
            mock_response.__enter__.return_value = mock_response

            with patch("urllib.request.urlopen", return_value=mock_response):
                response = client.get("/api/price/pepew-usdt")
                self.assertEqual(response.status_code, 200)
                data = response.get_json()
                self.assertEqual(data["price"], expected_price)

if __name__ == "__main__":
    unittest.main()
