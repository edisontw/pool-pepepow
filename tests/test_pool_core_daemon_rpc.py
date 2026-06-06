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

    def test_candidate_outcome_status(self):
        from daemon_rpc import candidate_outcome_status
        # Chain match states should take precedence
        self.assertEqual(candidate_outcome_status("match-found"), "chain-match-found")
        self.assertEqual(candidate_outcome_status("no-match-found"), "chain-match-not-found")
        self.assertEqual(candidate_outcome_status("check-error"), "check-error")

        # Disabled submissions should return submit-disabled
        self.assertEqual(
            candidate_outcome_status("not-checked", submit_status="submit-disabled-flag-off"),
            "submit-disabled"
        )

        # Unsent submissions should return not-submitted
        self.assertEqual(
            candidate_outcome_status("not-checked", submit_sent=False),
            "not-submitted"
        )

        # Submitted submissions when submit_sent is true or missing (backward compatibility)
        self.assertEqual(
            candidate_outcome_status("not-checked", submit_sent=True),
            "submitted"
        )
        self.assertEqual(
            candidate_outcome_status("not-checked"),
            "submitted"
        )

    def test_build_candidate_outcome_event_status_resolution(self):
        from daemon_rpc import build_candidate_outcome_event
        from datetime import datetime, timezone

        candidate_event = {
            "timestamp": "2026-05-27T16:46:28Z",
            "jobId": "job-000000000000001a",
            "candidateBlockHash": "000000029453ef330f44723c129dc780de00f6496635ce67323c42653148e27f",
            "submitblockRealSubmitStatus": "submit-disabled-flag-off",
            "submitblockSent": False,
        }

        outcome = build_candidate_outcome_event(
            candidate_event,
            recorded_at=datetime.now(timezone.utc)
        )
        self.assertEqual(outcome["candidateOutcomeStatus"], "submit-disabled")

        candidate_event_unsent = {
            "timestamp": "2026-05-27T16:46:28Z",
            "jobId": "job-000000000000001a",
            "candidateBlockHash": "000000029453ef330f44723c129dc780de00f6496635ce67323c42653148e27f",
            "submitblockRealSubmitStatus": "some-other-status",
            "submitblockSent": False,
        }
        outcome_unsent = build_candidate_outcome_event(
            candidate_event_unsent,
            recorded_at=datetime.now(timezone.utc)
        )
        self.assertEqual(outcome_unsent["candidateOutcomeStatus"], "not-submitted")

    def test_candidate_hash_block_target_comparison(self):
        # High-hash candidate hash: 00000002e37d152f579355c47a5f0317226b7e823f9415865da43195c5b41ef7
        # Block target: 0000000379120000000000000000000000000000000000000000000000000000
        candidate_hash = "00000002e37d152f579355c47a5f0317226b7e823f9415865da43195c5b41ef7"
        block_target = "0000000379120000000000000000000000000000000000000000000000000000"
        
        candidate_int = int(candidate_hash, 16)
        target_int = int(block_target, 16)
        
        # The pool-side comparison logic is: share_hash_int <= block_target_int
        meets_target = candidate_int <= target_int
        self.assertTrue(meets_target)

    def test_extract_block_reward_valid(self):
        from daemon_rpc import extract_block_reward
        block_data = {
            "tx": [
                {
                    "vout": [
                        {"value": 50000.0},
                        {"value": 250.0}
                    ]
                }
            ]
        }
        reward = extract_block_reward(block_data)
        self.assertEqual(reward, 50250.0)

    def test_extract_block_reward_missing_tx(self):
        from daemon_rpc import extract_block_reward
        self.assertIsNone(extract_block_reward({}))
        self.assertIsNone(extract_block_reward({"tx": []}))
        self.assertIsNone(extract_block_reward({"tx": "not-a-list"}))

    def test_extract_block_reward_invalid_coinbase(self):
        from daemon_rpc import extract_block_reward
        self.assertIsNone(extract_block_reward({"tx": [None]}))
        self.assertIsNone(extract_block_reward({"tx": [{"vout": "not-a-list"}]}))

    def test_extract_block_reward_invalid_vout(self):
        from daemon_rpc import extract_block_reward
        block_data = {
            "tx": [
                {
                    "vout": [
                        {"value": "invalid-value"},
                        {"value": 100.0}
                    ]
                }
            ]
        }
        self.assertIsNone(extract_block_reward(block_data))

    def test_get_block_calls_rpc_correctly(self):
        from unittest.mock import MagicMock
        client = DaemonRpcClient(
            rpc_url="http://127.0.0.1:12345",
            rpc_user="user",
            rpc_password="pwd",
            timeout_seconds=2
        )
        client.call = MagicMock(return_value={"hash": "abc", "tx": []})
        res = client.get_block("abc", verbosity=2)
        client.call.assert_called_once_with("getblock", ["abc", 2])
        self.assertEqual(res, {"hash": "abc", "tx": []})

    def test_get_block_fallback_on_boolean_error(self):
        from unittest.mock import MagicMock
        from daemon_rpc import DaemonRpcResponseError
        client = DaemonRpcClient(
            rpc_url="http://127.0.0.1:12345",
            rpc_user="user",
            rpc_password="pwd",
            timeout_seconds=2
        )
        
        # Mock call to fail with boolean type error first, then succeed on getblock with True,
        # then succeed on getrawtransaction
        def call_mock(method, params=None):
            if method == "getblock" and params == ["abc", 2]:
                raise DaemonRpcResponseError("JSON value is not a boolean as expected")
            if method == "getblock" and params == ["abc", True]:
                return {"hash": "abc", "tx": ["coinbase_txid", "other_txid"]}
            if method == "getrawtransaction" and params == ["coinbase_txid", 1]:
                return {"txid": "coinbase_txid", "vout": [{"value": 25000.0}]}
            raise RuntimeError(f"Unexpected RPC call: {method} {params}")

        client.call = MagicMock(side_effect=call_mock)
        res = client.get_block("abc", verbosity=2)
        self.assertEqual(res["hash"], "abc")
        self.assertEqual(res["tx"][0]["txid"], "coinbase_txid")
        self.assertEqual(res["tx"][0]["vout"][0]["value"], 25000.0)
        self.assertEqual(res["tx"][1], "other_txid")

    def test_get_raw_transaction(self):
        from unittest.mock import MagicMock
        client = DaemonRpcClient(
            rpc_url="http://127.0.0.1:12345",
            rpc_user="user",
            rpc_password="pwd",
            timeout_seconds=2
        )
        client.call = MagicMock(return_value={"txid": "txid123"})
        res = client.get_raw_transaction("txid123", verbosity=1)
        client.call.assert_called_once_with("getrawtransaction", ["txid123", 1])
        self.assertEqual(res, {"txid": "txid123"})

