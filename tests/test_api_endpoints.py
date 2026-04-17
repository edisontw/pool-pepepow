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
            "submitAcceptedCount": 5,
            "submitRejectedCount": 2,
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

    def test_blocks_endpoint_uses_runtime_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "runtime.json"
            runtime_payload = make_runtime_snapshot()
            runtime_payload["generatedAt"] = "2999-01-01T00:00:00Z"
            runtime_path.write_text(
                json.dumps(runtime_payload), encoding="utf-8"
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

    def test_payments_endpoint_is_placeholder(self):
        app = create_app(
            make_config(Path("/tmp/does-not-exist.json"), FALLBACK_SNAPSHOT_PATH)
        )
        client = app.test_client()
        response = client.get("/api/payments")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "placeholder")
        self.assertEqual(payload["dataStatus"], "fallback")
        self.assertEqual(payload["items"], [])

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
            self.assertEqual(health_payload["submitAcceptedCount"], 5)
            self.assertEqual(health_payload["submitRejectedCount"], 2)
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


if __name__ == "__main__":
    unittest.main()
