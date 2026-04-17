from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

POOL_CORE_DIR = Path(__file__).resolve().parents[1] / "apps" / "pool-core"
sys.path.insert(0, str(POOL_CORE_DIR))


def _load_module(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, POOL_CORE_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


pool_core_config = _load_module("pool_core_config", "config.py")
sys.modules["config"] = pool_core_config
stratum_ingress = _load_module("pool_core_stratum_ingress", "stratum_ingress.py")
pool_core_daemon_rpc = sys.modules["daemon_rpc"]

PoolCoreConfig = pool_core_config.PoolCoreConfig
StratumIngressService = stratum_ingress.StratumIngressService
DaemonRpcUnavailableError = pool_core_daemon_rpc.DaemonRpcUnavailableError
SessionStats = stratum_ingress.SessionStats
SubmitAssessment = stratum_ingress.SubmitAssessment


class SuccessfulTemplateRpcClient:
    def get_block_template(self) -> dict[str, object]:
        return {
            "previousblockhash": "1" * 64,
            "transactions": [
                {
                    "hash": "2" * 64,
                }
            ],
            "coinbaseaux": {"flags": "f00d"},
            "coinbasevalue": 5_000_000_000,
            "bits": "1c0ffff0",
            "target": "0f" * 32,
            "height": 123456,
            "version": 536870912,
            "curtime": 1713225600,
        }


class FailingTemplateRpcClient:
    def get_block_template(self) -> dict[str, object]:
        raise DaemonRpcUnavailableError("template RPC unavailable")


class StratumIngressTests(unittest.IsolatedAsyncioTestCase):
    def test_pepepow_header_hash_matches_known_chain_vector(self):
        header_hex = (
            "0040002038e31388c54124146478ff691985eecd02610db91efbc9cd7aabca4900000000"
            "07647f0508057dbf8c99ddaa87543c04e31dfe3f383e7386903d50c91728fabe830be169"
            "71e3021da96d9d33"
        )
        expected_hash = (
            "00000001fb895a82973fca52938848908d6a6cb3c0dfb93995dc61020ced0a6b"
        )
        share_hash = stratum_ingress._calculate_pepepow_share_hash(
            bytes.fromhex(header_hex)
        )
        self.assertEqual(share_hash.hex(), expected_hash)

    async def test_authorize_pushes_synthetic_difficulty_and_notify(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                synthetic_job_interval_seconds=30.0,
            )
            service = StratumIngressService(config)
            await service.start()

            reader = writer = None
            try:
                reader, writer = await self._open_client(service)
                subscribe_response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 1,
                        "method": "mining.subscribe",
                        "params": ["test-miner/1.0"],
                    },
                )
                subscriptions = subscribe_response["result"][0]
                self.assertEqual(
                    [entry[0] for entry in subscriptions],
                    [
                        "mining.set_difficulty",
                        "mining.notify",
                    ],
                )
                self.assertEqual(len({entry[1] for entry in subscriptions}), 1)
                self.assertEqual(subscribe_response["result"][2], 4)

                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": [
                                "PEPEPOW1KnownWalletAddress000000.rig01",
                                "x",
                            ],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                authorize_response = await self._read_json(reader)
                difficulty_message = await self._read_json(reader)
                notify_message = await self._read_json(reader)

                self.assertTrue(authorize_response["result"])
                self.assertEqual(difficulty_message["method"], "mining.set_difficulty")
                self.assertEqual(
                    difficulty_message["params"],
                    [config.hashrate_assumed_share_difficulty],
                )
                self.assertEqual(notify_message["method"], "mining.notify")
                self.assertEqual(len(notify_message["params"]), 9)
                self.assertTrue(notify_message["params"][8])

                submit_response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            notify_message["params"][0],
                            notify_message["params"][7],
                        ),
                    },
                )
                self.assertTrue(submit_response["result"])

                await self._wait_for(
                    lambda: len(self._read_share_events(config.activity_log_path)) == 1
                )
                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "windowReplaySequenceFloor"
                        )
                        == 1
                    )
                )

                share_lines = config.activity_log_path.read_text(encoding="utf-8").splitlines()
                self.assertEqual(len(share_lines), 1)
                share_event = json.loads(share_lines[0])
                self.assertEqual(
                    share_event["wallet"], "PEPEPOW1KnownWalletAddress000000"
                )
                self.assertEqual(share_event["worker"], "rig01")
                self.assertEqual(share_event["jobId"], notify_message["params"][0])
                self.assertEqual(
                    share_event["difficulty"],
                    config.hashrate_assumed_share_difficulty,
                )
                self.assertEqual(share_event["jobStatus"], "current")
                self.assertTrue(share_event["syntheticWork"])
                self.assertFalse(share_event["blockchainVerified"])
                self.assertEqual(
                    share_event["shareValidationMode"], "structural-skeleton"
                )

                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "windowReplaySequenceFloor"
                        )
                        == 1
                    )
                )
                activity_snapshot = self._load_json(config.activity_snapshot_output_path)
                self.assertEqual(
                    activity_snapshot["meta"]["syntheticJobMode"],
                    "synthetic-stratum-v1",
                )
                self.assertEqual(
                    activity_snapshot["meta"]["shareValidationMode"],
                    "structural-skeleton",
                )
                self.assertEqual(
                    activity_snapshot["meta"]["windowReplaySequenceFloor"],
                    1,
                )
                self.assertEqual(activity_snapshot["pool"]["activeMiners"], 1)
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_authorized_connection_receives_periodic_notify_refresh(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                synthetic_job_interval_seconds=1.0,
            )
            service = StratumIngressService(config)
            await service.start()

            reader = writer = None
            try:
                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                authorize_response = await self._read_json(reader)
                first_notify = None
                for _ in range(2):
                    message = await self._read_json(reader)
                    if message.get("method") == "mining.notify":
                        first_notify = message
                self.assertTrue(authorize_response["result"])
                self.assertIsNotNone(first_notify)

                periodic_notify = await asyncio.wait_for(self._read_json(reader), timeout=2.5)
                self.assertEqual(periodic_notify["method"], "mining.notify")
                self.assertNotEqual(periodic_notify["params"][0], first_notify["params"][0])
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_daemon_template_mode_populates_job_cache_and_status(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                template_mode="daemon-template",
                template_fetch_interval_seconds=5.0,
            )
            service = StratumIngressService(
                config,
                rpc_client=SuccessfulTemplateRpcClient(),
            )
            await service.start()

            reader = writer = None
            try:
                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "templateFetchStatus"
                        )
                        == "ok"
                    )
                )

                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)

                self.assertEqual(notify_message["method"], "mining.notify")
                self.assertEqual(notify_message["params"][1], "1" * 64)
                self.assertNotEqual(
                    notify_message["params"][2], stratum_ingress.SYNTHETIC_COINB1
                )
                self.assertNotEqual(
                    notify_message["params"][3], stratum_ingress.SYNTHETIC_COINB2
                )
                self.assertEqual(len(notify_message["params"][4]), 1)
                self.assertEqual(notify_message["params"][6], "1c0ffff0")
                self.assertEqual(notify_message["params"][7], "661dbf80")

                submit_response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            notify_message["params"][0],
                            notify_message["params"][7],
                        ),
                    },
                )
                self.assertTrue(submit_response["result"])

                await self._wait_for(
                    lambda: len(self._read_share_events(config.activity_log_path)) == 1
                )
                share_event = json.loads(self._read_share_events(config.activity_log_path)[0])
                self.assertEqual(share_event["jobSource"], "daemon-template")
                self.assertFalse(share_event["syntheticWork"])
                self.assertIsNotNone(share_event["templateAnchor"])
                self.assertEqual(share_event["targetContext"]["bits"], "1c0ffff0")
                self.assertEqual(
                    share_event["preimageContext"]["source"], "template-derived"
                )
                self.assertEqual(
                    share_event["preimageContext"]["merkleBranchLength"], 1
                )
                self.assertEqual(
                    share_event["targetValidationStatus"], "candidate-possible"
                )
                self.assertTrue(share_event["candidatePossible"])
                self.assertEqual(
                    share_event["shareHashValidationStatus"], "share-hash-invalid"
                )
                self.assertFalse(share_event["shareHashValid"])

                activity_snapshot = self._load_json(config.activity_snapshot_output_path)
                self.assertEqual(
                    activity_snapshot["meta"]["templateModeConfigured"],
                    "daemon-template",
                )
                self.assertEqual(
                    activity_snapshot["meta"]["templateModeEffective"],
                    "daemon-template",
                )
                self.assertEqual(
                    activity_snapshot["meta"]["templateDaemonRpcStatus"],
                    "reachable",
                )
                self.assertEqual(
                    activity_snapshot["meta"]["templateFetchStatus"],
                    "ok",
                )
                self.assertGreaterEqual(activity_snapshot["meta"]["activeJobCount"], 1)
                self.assertEqual(
                    activity_snapshot["meta"]["submitCandidatePossibleCount"], 1
                )
                self.assertEqual(
                    activity_snapshot["meta"]["submitTargetValidationCounts"][
                        "candidate-possible"
                    ],
                    1,
                )
                self.assertEqual(
                    activity_snapshot["meta"]["submitShareHashValidationCounts"][
                        "share-hash-invalid"
                    ],
                    1,
                )
                self.assertEqual(
                    activity_snapshot["jobs"]["active"][0]["source"],
                    "daemon-template",
                )
                self.assertEqual(
                    activity_snapshot["jobs"]["active"][0]["preimageContext"][
                        "source"
                    ],
                    "template-derived",
                )
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_submit_with_share_hash_valid_is_classified_without_rejection(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                template_mode="daemon-template",
                template_fetch_interval_seconds=5.0,
            )
            service = StratumIngressService(
                config,
                rpc_client=SuccessfulTemplateRpcClient(),
            )
            await service.start()

            reader = writer = None
            try:
                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "templateFetchStatus"
                        )
                        == "ok"
                    )
                )

                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)
                job_id = notify_message["params"][0]
                cached_job = service._job_manager.get_job(job_id)
                assert cached_job is not None
                target_context = dict(cached_job.target_context)
                target_context["target"] = "f" * 64
                service._job_manager._jobs[job_id] = replace(
                    cached_job,
                    target_context=target_context,
                )

                submit_response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            job_id,
                            notify_message["params"][7],
                        ),
                    },
                )
                self.assertTrue(submit_response["result"])

                await self._wait_for(
                    lambda: len(self._read_share_events(config.activity_log_path)) == 1
                )
                share_event = json.loads(self._read_share_events(config.activity_log_path)[0])
                self.assertEqual(
                    share_event["shareHashValidationStatus"], "share-hash-valid"
                )
                self.assertTrue(share_event["shareHashValid"])
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_daemon_template_failure_falls_back_without_breaking_submit(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                template_mode="daemon-template",
                template_fetch_interval_seconds=5.0,
            )
            service = StratumIngressService(
                config,
                rpc_client=FailingTemplateRpcClient(),
            )
            await service.start()

            reader = writer = None
            try:
                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "templateFetchStatus"
                        )
                        == "error"
                    )
                )

                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)

                self.assertEqual(notify_message["method"], "mining.notify")
                self.assertEqual(notify_message["params"][1], "0" * 64)

                submit_response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            notify_message["params"][0],
                            notify_message["params"][7],
                        ),
                    },
                )
                self.assertTrue(submit_response["result"])

                await self._wait_for(
                    lambda: len(self._read_share_events(config.activity_log_path)) == 1
                )
                share_event = json.loads(self._read_share_events(config.activity_log_path)[0])
                self.assertEqual(share_event["jobSource"], "synthetic")
                self.assertTrue(share_event["syntheticWork"])

                activity_snapshot = self._load_json(config.activity_snapshot_output_path)
                self.assertEqual(
                    activity_snapshot["meta"]["templateModeEffective"],
                    "daemon-template-fallback-synthetic",
                )
                self.assertEqual(
                    activity_snapshot["meta"]["templateDaemonRpcStatus"],
                    "unreachable",
                )
                self.assertEqual(
                    activity_snapshot["meta"]["templateFetchStatus"],
                    "error",
                )
                self.assertGreaterEqual(activity_snapshot["meta"]["activeJobCount"], 1)
                self.assertEqual(
                    activity_snapshot["jobs"]["active"][0]["source"],
                    "synthetic",
                )
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_submit_with_missing_target_context_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                template_mode="daemon-template",
                template_fetch_interval_seconds=5.0,
            )
            service = StratumIngressService(
                config,
                rpc_client=SuccessfulTemplateRpcClient(),
            )
            await service.start()

            reader = writer = None
            try:
                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "templateFetchStatus"
                        )
                        == "ok"
                    )
                )

                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)
                job_id = notify_message["params"][0]
                cached_job = service._job_manager.get_job(job_id)
                assert cached_job is not None
                service._job_manager._jobs[job_id] = replace(
                    cached_job,
                    target_context={},
                )

                response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            job_id,
                            notify_message["params"][7],
                        ),
                    },
                )
                self.assertFalse(response["result"])

                await self._wait_for(
                    lambda: self._read_share_events(config.activity_log_path)
                )
                share_event = json.loads(
                    self._read_share_events(config.activity_log_path)[0]
                )
                self.assertEqual(
                    share_event["rejectReason"], "target-context-missing"
                )
                self.assertEqual(
                    share_event["targetValidationStatus"], "target-context-missing"
                )
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_submit_with_mismatched_target_context_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                template_mode="daemon-template",
                template_fetch_interval_seconds=5.0,
            )
            service = StratumIngressService(
                config,
                rpc_client=SuccessfulTemplateRpcClient(),
            )
            await service.start()

            reader = writer = None
            try:
                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "templateFetchStatus"
                        )
                        == "ok"
                    )
                )

                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)

                response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            notify_message["params"][0],
                            "00000000",
                        ),
                    },
                )
                self.assertFalse(response["result"])

                await self._wait_for(
                    lambda: self._read_share_events(config.activity_log_path)
                )
                share_event = json.loads(
                    self._read_share_events(config.activity_log_path)[0]
                )
                self.assertEqual(
                    share_event["rejectReason"], "target-context-mismatch"
                )
                self.assertEqual(
                    share_event["targetValidationStatus"], "target-context-mismatch"
                )
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_submit_with_preimage_missing_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                template_mode="daemon-template",
                template_fetch_interval_seconds=5.0,
            )
            service = StratumIngressService(
                config,
                rpc_client=SuccessfulTemplateRpcClient(),
            )
            await service.start()

            reader = writer = None
            try:
                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "templateFetchStatus"
                        )
                        == "ok"
                    )
                )

                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)
                job_id = notify_message["params"][0]
                cached_job = service._job_manager.get_job(job_id)
                assert cached_job is not None
                service._job_manager._jobs[job_id] = replace(
                    cached_job,
                    prevhash=None,
                )

                response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            job_id,
                            notify_message["params"][7],
                        ),
                    },
                )
                self.assertFalse(response["result"])

                await self._wait_for(
                    lambda: self._read_share_events(config.activity_log_path)
                )
                share_event = json.loads(
                    self._read_share_events(config.activity_log_path)[0]
                )
                self.assertEqual(share_event["rejectReason"], "preimage-missing")
                self.assertEqual(
                    share_event["shareHashValidationStatus"], "preimage-missing"
                )
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_submit_with_preimage_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                template_mode="daemon-template",
                template_fetch_interval_seconds=5.0,
            )
            service = StratumIngressService(
                config,
                rpc_client=SuccessfulTemplateRpcClient(),
            )
            await service.start()

            reader = writer = None
            try:
                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "templateFetchStatus"
                        )
                        == "ok"
                    )
                )

                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)
                issued_ntime = int(notify_message["params"][7], 16)
                mismatched_ntime = f"{issued_ntime + 1:08x}"

                response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            notify_message["params"][0],
                            mismatched_ntime,
                        ),
                    },
                )
                self.assertFalse(response["result"])

                await self._wait_for(
                    lambda: self._read_share_events(config.activity_log_path)
                )
                share_event = json.loads(
                    self._read_share_events(config.activity_log_path)[0]
                )
                self.assertEqual(share_event["rejectReason"], "preimage-mismatch")
                self.assertEqual(
                    share_event["shareHashValidationStatus"], "preimage-mismatch"
                )
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_extranonce_subscribe_is_a_noop_success(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(tmp_path)
            service = StratumIngressService(config)
            await service.start()

            reader = writer = None
            try:
                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                extranonce_response = await self._rpc_call(
                    reader,
                    writer,
                    {"id": 2, "method": "mining.extranonce.subscribe", "params": []},
                )
                self.assertTrue(extranonce_response["result"])
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_submit_with_previous_job_id_is_tagged_previous(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                synthetic_job_interval_seconds=1.0,
            )
            service = StratumIngressService(config)
            await service.start()

            reader = writer = None
            try:
                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                first_notify = await self._read_json(reader)
                second_notify = await asyncio.wait_for(self._read_json(reader), timeout=2.5)

                self.assertEqual(first_notify["method"], "mining.notify")
                self.assertEqual(second_notify["method"], "mining.notify")

                response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            first_notify["params"][0],
                            first_notify["params"][7],
                        ),
                    },
                )
                self.assertTrue(response["result"])

                await self._wait_for(
                    lambda: self._read_share_events(config.activity_log_path)
                )
                share_event = json.loads(
                    self._read_share_events(config.activity_log_path)[0]
                )
                self.assertEqual(share_event["jobStatus"], "previous")
                self.assertEqual(share_event["jobId"], first_notify["params"][0])
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_submit_with_malformed_params_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(tmp_path)
            service = StratumIngressService(config)
            await service.start()

            reader = writer = None
            try:
                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                await self._read_json(reader)

                response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "", "extra"],
                    },
                )
                self.assertFalse(response["result"])

                await self._wait_for(
                    lambda: self._read_share_events(config.activity_log_path)
                )
                share_event = json.loads(
                    self._read_share_events(config.activity_log_path)[0]
                )
                self.assertEqual(share_event["jobStatus"], "malformed")
                self.assertEqual(share_event["status"], "rejected")
                self.assertEqual(share_event["rejectReason"], "malformed-submit")
                self.assertIsNone(share_event["jobId"])
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_submit_with_unknown_job_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(tmp_path)
            service = StratumIngressService(config)
            await service.start()

            reader = writer = None
            try:
                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                await self._read_json(reader)

                response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": [
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            "job-not-known-here",
                            "extra",
                            "ntime",
                            "nonce",
                        ],
                    },
                )
                self.assertFalse(response["result"])

                await self._wait_for(
                    lambda: self._read_share_events(config.activity_log_path)
                )
                share_event = json.loads(
                    self._read_share_events(config.activity_log_path)[0]
                )
                self.assertEqual(share_event["jobStatus"], "unknown")
                self.assertEqual(share_event["status"], "rejected")
                self.assertEqual(share_event["rejectReason"], "unknown-job")
                self.assertEqual(share_event["jobId"], "job-not-known-here")
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_restart_like_unknown_job_id_gets_backlog_detail(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(tmp_path)
            service = StratumIngressService(config)
            await service.start()

            reader = writer = None
            try:
                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)

                self.assertEqual(notify_message["method"], "mining.notify")

                response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": [
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            "job-0000000000000010",
                            "extra",
                            "ntime",
                            "nonce",
                        ],
                    },
                )
                self.assertFalse(response["result"])

                await self._wait_for(
                    lambda: self._read_share_events(config.activity_log_path)
                )
                share_event = json.loads(
                    self._read_share_events(config.activity_log_path)[0]
                )
                self.assertEqual(share_event["jobStatus"], "unknown")
                self.assertEqual(share_event["rejectReason"], "unknown-job")
                self.assertEqual(
                    share_event["rejectDetail"],
                    "job id not present in active or retired cache; possible restart backlog from prior ingress process",
                )
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_submit_with_stale_job_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                synthetic_job_interval_seconds=30.0,
                template_job_ttl_seconds=1,
            )
            service = StratumIngressService(config)
            await service.start()

            reader = writer = None
            try:
                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)
                await asyncio.sleep(1.2)

                response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            notify_message["params"][0],
                            notify_message["params"][7],
                        ),
                    },
                )
                self.assertFalse(response["result"])

                await self._wait_for(
                    lambda: self._read_share_events(config.activity_log_path)
                )
                share_event = json.loads(
                    self._read_share_events(config.activity_log_path)[0]
                )
                self.assertEqual(share_event["jobStatus"], "stale")
                self.assertEqual(share_event["rejectReason"], "stale-job")
                self.assertEqual(share_event["status"], "rejected")
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_duplicate_submit_is_rejected_within_bounded_window(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(tmp_path)
            service = StratumIngressService(config)
            await service.start()

            reader = writer = None
            try:
                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                notify_message = await self._read_json(reader)

                submit_params = self._submit_params(
                    "PEPEPOW1KnownWalletAddress000000.rig01",
                    notify_message["params"][0],
                    notify_message["params"][7],
                )
                first_response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 3,
                        "method": "mining.submit",
                        "params": submit_params,
                    },
                )
                duplicate_response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": 4,
                        "method": "mining.submit",
                        "params": submit_params,
                    },
                )

                self.assertTrue(first_response["result"])
                self.assertFalse(duplicate_response["result"])

                await self._wait_for(
                    lambda: len(self._read_share_events(config.activity_log_path)) == 2
                )
                share_events = [
                    json.loads(line)
                    for line in self._read_share_events(config.activity_log_path)
                ]
                self.assertEqual(share_events[0]["status"], "accepted")
                self.assertEqual(share_events[1]["status"], "rejected")
                self.assertEqual(
                    share_events[1]["rejectReason"], "duplicate-submit"
                )
                self.assertTrue(share_events[1]["duplicateSubmit"])
                await self._wait_for(
                    lambda: (
                        config.activity_snapshot_output_path.exists()
                        and self._load_json(config.activity_snapshot_output_path)["meta"].get(
                            "submitRejectedCount"
                        )
                        == 1
                    )
                )
                activity_snapshot = self._load_json(config.activity_snapshot_output_path)
                self.assertEqual(
                    activity_snapshot["meta"]["submitAcceptedCount"], 1
                )
                self.assertEqual(
                    activity_snapshot["meta"]["submitRejectedCount"], 1
                )
                self.assertEqual(
                    activity_snapshot["meta"]["submitRejectReasonCounts"][
                        "duplicate-submit"
                    ],
                    1,
                )
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_repeated_unknown_reject_logs_are_summarized(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(tmp_path)
            service = StratumIngressService(config)
            session_stats = SessionStats()
            assessment = SubmitAssessment(
                job_status="unknown",
                submit_job_id="job-0000000000000010",
                cached_job=None,
                accepted=False,
                reject_reason="unknown-job",
                detail="job id not present in active or retired cache; possible restart backlog from prior ingress process",
            )

            with self.assertLogs("pepepow.stratum_ingress", level="WARNING") as captured:
                service._log_submit_outcome(
                    session_id="session-1",
                    remote_address="127.0.0.1:9999",
                    share_count=1,
                    submit_job_id=assessment.submit_job_id,
                    current_job_id="job-0000000000000003",
                    previous_job_id="job-0000000000000002",
                    assessment=assessment,
                    session_stats=session_stats,
                )
                service._log_submit_outcome(
                    session_id="session-1",
                    remote_address="127.0.0.1:9999",
                    share_count=2,
                    submit_job_id=assessment.submit_job_id,
                    current_job_id="job-0000000000000003",
                    previous_job_id="job-0000000000000002",
                    assessment=assessment,
                    session_stats=session_stats,
                )
                service._flush_reject_log_summary(
                    session_id="session-1",
                    remote_address="127.0.0.1:9999",
                    session_stats=session_stats,
                )

            self.assertEqual(len(captured.records), 2)
            self.assertIn("Submit rejected:", captured.output[0])
            self.assertIn("Submit rejected repeatedly:", captured.output[1])
            self.assertIn("suppressedCount=1", captured.output[1])

    async def test_stop_closes_active_client_after_notify_loop_started(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                synthetic_job_interval_seconds=1.0,
            )
            service = StratumIngressService(config)
            await service.start()

            reader = writer = None
            try:
                reader, writer = await self._open_client(service)
                await self._rpc_call(
                    reader,
                    writer,
                    {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
                )
                writer.write(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "mining.authorize",
                            "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()

                await self._read_json(reader)
                await self._read_json(reader)
                await self._read_json(reader)

                await asyncio.wait_for(service.stop(), timeout=2.0)
                self.assertEqual(await asyncio.wait_for(reader.readline(), timeout=2.0), b"")
                writer.close()
                await writer.wait_closed()
                writer = None
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.stop()

    async def test_rotation_and_restart_recovery_preserve_activity(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                activity_log_rotate_bytes=900,
                activity_log_retention_files=4,
            )

            pre_snapshot = await self._run_share_session(config, share_count=24)
            rotated_logs = sorted(tmp_path.glob("shares.*-*.jsonl"))
            self.assertGreaterEqual(len(rotated_logs), 1)
            self.assertTrue(
                all(
                    re.fullmatch(r"shares\.\d{20}-\d{20}\.jsonl", path.name)
                    for path in rotated_logs
                )
            )

            restart_service = StratumIngressService(config)
            await restart_service.start()
            try:
                post_snapshot = self._load_json(config.activity_snapshot_output_path)
            finally:
                await restart_service.stop()

            self.assertEqual(
                pre_snapshot["miners"]["PEPEPOW1KnownWalletAddress000000"]["summary"][
                    "acceptedShares"
                ],
                post_snapshot["miners"]["PEPEPOW1KnownWalletAddress000000"]["summary"][
                    "acceptedShares"
                ],
            )
            self.assertEqual(
                pre_snapshot["pool"]["rolling"]["15m"]["shareCount"],
                post_snapshot["pool"]["rolling"]["15m"]["shareCount"],
            )
            self.assertEqual(pre_snapshot["meta"]["warningCount"], 0)
            self.assertEqual(post_snapshot["meta"]["warningCount"], 0)

    async def test_replay_window_boundary_warns_when_retention_truncates_tail(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config = self._make_config(
                tmp_path,
                activity_log_rotate_bytes=200,
                activity_log_retention_files=1,
            )

            pre_snapshot = await self._run_share_session(
                config,
                share_count=60,
                submit_pause_seconds=0.02,
            )
            self.assertEqual(pre_snapshot["meta"]["warningCount"], 0)
            rotated_logs = list(tmp_path.glob("shares.*-*.jsonl"))
            self.assertEqual(len(rotated_logs), 1)

            restart_service = StratumIngressService(config)
            await restart_service.start()
            try:
                post_snapshot = self._load_json(config.activity_snapshot_output_path)
            finally:
                await restart_service.stop()

            self.assertGreater(post_snapshot["meta"]["warningCount"], 0)
            self.assertEqual(
                pre_snapshot["miners"]["PEPEPOW1KnownWalletAddress000000"]["summary"][
                    "acceptedShares"
                ],
                post_snapshot["miners"]["PEPEPOW1KnownWalletAddress000000"]["summary"][
                    "acceptedShares"
                ],
            )
            self.assertLess(
                post_snapshot["pool"]["rolling"]["15m"]["shareCount"],
                pre_snapshot["pool"]["rolling"]["15m"]["shareCount"],
            )

    async def _run_share_session(
        self,
        config: PoolCoreConfig,
        *,
        share_count: int,
        submit_pause_seconds: float = 0.0,
    ) -> dict:
        service = StratumIngressService(config)
        await service.start()

        reader = writer = None
        try:
            reader, writer = await self._open_client(service)
            await self._rpc_call(
                reader,
                writer,
                {"id": 1, "method": "mining.subscribe", "params": ["test-miner/1.0"]},
            )
            writer.write(
                json.dumps(
                    {
                        "id": 2,
                        "method": "mining.authorize",
                        "params": ["PEPEPOW1KnownWalletAddress000000.rig01", "x"],
                    }
                ).encode("utf-8")
                + b"\n"
            )
            await writer.drain()

            await self._read_json(reader)
            await self._read_json(reader)
            notify_message = await self._read_json(reader)
            self.assertEqual(notify_message["method"], "mining.notify")

            for request_id in range(3, 3 + share_count):
                response = await self._rpc_call(
                    reader,
                    writer,
                    {
                        "id": request_id,
                        "method": "mining.submit",
                        "params": self._submit_params(
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            notify_message["params"][0],
                            notify_message["params"][7],
                            extranonce2=f"{request_id:08x}",
                            nonce=f"{(request_id + 1):08x}",
                        ),
                    },
                )
                self.assertTrue(response["result"])
                if submit_pause_seconds > 0:
                    await asyncio.sleep(submit_pause_seconds)

            writer.close()
            await writer.wait_closed()
            writer = None
            await service.stop()
            return self._load_json(config.activity_snapshot_output_path)
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()

    async def _open_client(self, service: StratumIngressService):
        assert service._server is not None
        host, port = service._server.sockets[0].getsockname()[:2]
        return await asyncio.open_connection(host, port)

    async def _rpc_call(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        payload: dict[str, object],
    ) -> dict:
        writer.write(json.dumps(payload).encode("utf-8") + b"\n")
        await writer.drain()
        request_id = payload["id"]

        while True:
            response = await self._read_json(reader)
            if response.get("id") == request_id:
                return response

    async def _read_json(self, reader: asyncio.StreamReader) -> dict:
        return json.loads((await reader.readline()).decode("utf-8"))

    def _submit_params(
        self,
        login: str,
        job_id: str,
        ntime: str,
        *,
        extranonce2: str = "00000001",
        nonce: str = "00000001",
    ) -> list[str]:
        return [login, job_id, extranonce2, ntime, nonce]

    async def _wait_for(self, predicate, timeout: float = 3.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if predicate():
                return
            await asyncio.sleep(0.05)
        self.fail("Timed out waiting for predicate")

    def _load_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _read_share_events(self, path: Path) -> list[str]:
        if not path.exists():
            return []
        return path.read_text(encoding="utf-8").splitlines()

    def _make_config(
        self,
        tmp_path: Path,
        *,
        synthetic_job_interval_seconds: float = 30.0,
        template_mode: str = "synthetic",
        template_fetch_interval_seconds: float = 15.0,
        template_job_ttl_seconds: int = 180,
        activity_log_rotate_bytes: int = 32 * 1024 * 1024,
        activity_log_retention_files: int = 8,
    ) -> PoolCoreConfig:
        return PoolCoreConfig(
            coin_name="PEPEPOW",
            algorithm="hoohashv110-pepew",
            fee_percent=1.0,
            min_payout=10.0,
            stratum_host="pool.example.com",
            stratum_port=3333,
            stratum_tls=False,
            stratum_bind_host="127.0.0.1",
            stratum_bind_port=0,
            rpc_url="http://127.0.0.1:8834",
            rpc_user="",
            rpc_password="",
            rpc_timeout_seconds=1.0,
            snapshot_output_path=tmp_path / "runtime.json",
            activity_snapshot_output_path=tmp_path / "activity-snapshot.json",
            snapshot_interval_seconds=60,
            activity_snapshot_interval_seconds=0.1,
            rpc_cache_ttl_seconds=1,
            recent_blocks_limit=1,
            stale_after_seconds=180,
            producer_name="test",
            activity_log_path=tmp_path / "shares.jsonl",
            activity_window_seconds=900,
            activity_mode="testing-local-ingest",
            stratum_queue_maxsize=1000,
            hashrate_assumed_share_difficulty=1.0,
            synthetic_job_interval_seconds=synthetic_job_interval_seconds,
            template_mode=template_mode,
            template_fetch_interval_seconds=template_fetch_interval_seconds,
            template_job_ttl_seconds=template_job_ttl_seconds,
            template_job_cache_size=64,
            activity_log_rotate_bytes=activity_log_rotate_bytes,
            activity_log_retention_files=activity_log_retention_files,
        )


if __name__ == "__main__":
    unittest.main()
