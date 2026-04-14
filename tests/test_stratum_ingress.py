from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import sys
import tempfile
import unittest
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

PoolCoreConfig = pool_core_config.PoolCoreConfig
StratumIngressService = stratum_ingress.StratumIngressService


class StratumIngressTests(unittest.IsolatedAsyncioTestCase):
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
                        "params": [
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            notify_message["params"][0],
                            "extra",
                            "ntime",
                            "nonce",
                        ],
                    },
                )
                self.assertTrue(submit_response["result"])

                await self._wait_for(lambda: config.activity_log_path.exists())
                await self._wait_for(lambda: config.activity_snapshot_output_path.exists())

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
                self.assertTrue(share_event["syntheticWork"])
                self.assertFalse(share_event["blockchainVerified"])
                self.assertEqual(share_event["shareValidationMode"], "none")

                activity_snapshot = self._load_json(config.activity_snapshot_output_path)
                self.assertEqual(
                    activity_snapshot["meta"]["syntheticJobMode"],
                    "synthetic-stratum-v1",
                )
                self.assertEqual(
                    activity_snapshot["meta"]["shareValidationMode"],
                    "none",
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

            pre_snapshot = await self._run_share_session(config, share_count=60)
            self.assertEqual(pre_snapshot["meta"]["warningCount"], 0)
            rotated_logs = list(tmp_path.glob("shares.*-*.jsonl"))
            self.assertEqual(len(rotated_logs), 1)
            self.assertGreater(int(rotated_logs[0].name.split(".")[1].split("-")[0]), 1)

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
                        "params": [
                            "PEPEPOW1KnownWalletAddress000000.rig01",
                            notify_message["params"][0],
                            f"extra-{request_id}",
                            f"ntime-{request_id}",
                            f"nonce-{request_id}",
                        ],
                    },
                )
                self.assertTrue(response["result"])

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

    async def _wait_for(self, predicate, timeout: float = 3.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if predicate():
                return
            await asyncio.sleep(0.05)
        self.fail("Timed out waiting for predicate")

    def _load_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _make_config(
        self,
        tmp_path: Path,
        *,
        synthetic_job_interval_seconds: float = 30.0,
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
            activity_log_rotate_bytes=activity_log_rotate_bytes,
            activity_log_retention_files=activity_log_retention_files,
        )


if __name__ == "__main__":
    unittest.main()
