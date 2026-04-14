from __future__ import annotations

import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
POOL_CORE_DIR = Path(__file__).resolve().parents[1] / "apps" / "pool-core"
sys.path.insert(0, str(TESTS_DIR))
sys.path.insert(0, str(POOL_CORE_DIR))

from daemon_rpc import DaemonRpcClient, DaemonRpcUnavailableError  # noqa: E402
from rpc_fixture_server import RpcFixtureServer  # noqa: E402


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "daemon"


class DaemonRpcClientTests(unittest.TestCase):
    def setUp(self):
        self.server = RpcFixtureServer(FIXTURE_DIR)
        self.server.start()

    def tearDown(self):
        self.server.stop()

    def test_get_blockchain_info_uses_cache(self):
        client = DaemonRpcClient(
            rpc_url=self.server.url,
            rpc_user="test-user",
            rpc_password="test-password",
            timeout_seconds=2,
            cache_ttl_seconds=60,
        )

        first = client.get_blockchain_info()
        second = client.get_blockchain_info()

        self.assertEqual(first["blocks"], 4355984)
        self.assertEqual(second["blocks"], 4355984)
        self.assertEqual(self.server.request_counts["getblockchaininfo"], 1)

    def test_recent_block_headers_are_sorted_descending(self):
        client = DaemonRpcClient(
            rpc_url=self.server.url,
            rpc_user="test-user",
            rpc_password="test-password",
            timeout_seconds=2,
            cache_ttl_seconds=60,
        )

        headers = client.get_recent_block_headers(4355984, 3)
        heights = [header["height"] for header in headers]
        self.assertEqual(heights, [4355984, 4355983, 4355982])

    def test_bad_credentials_raise_unavailable(self):
        client = DaemonRpcClient(
            rpc_url=self.server.url,
            rpc_user="wrong-user",
            rpc_password="wrong-password",
            timeout_seconds=2,
            cache_ttl_seconds=60,
        )

        with self.assertRaises(DaemonRpcUnavailableError):
            client.get_blockchain_info()
