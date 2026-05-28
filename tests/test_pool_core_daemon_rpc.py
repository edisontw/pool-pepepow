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

