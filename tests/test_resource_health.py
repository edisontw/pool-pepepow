from __future__ import annotations

import sys
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops" / "scripts"))
import resource_health  # noqa: E402


class ResourceHealthTests(unittest.TestCase):
    def test_root_filesystem_warning_thresholds(self):
        self.assertIsNone(resource_health.filesystem_warning(79.99))
        self.assertEqual(resource_health.filesystem_warning(80.0), "root-filesystem-usage-high")
        self.assertEqual(resource_health.filesystem_warning(89.99), "root-filesystem-usage-high")
        self.assertEqual(resource_health.filesystem_warning(90.0), "root-filesystem-usage-critical")

    def test_attribution_health_joins_paid_state_and_only_flags_recent_unpaid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc).timestamp()
            rounds_path = root / "rounds.json"
            candidates_path = root / "payout-candidates.json"
            payments_path = root / "payments.json"
            ledger_path = root / "ledger.jsonl"
            rounds_path.write_text(json.dumps({"rounds": [
                {"candidate_hash": "a", "status": "confirmed", "submit_timestamp": "2026-10-08T11:30:00Z",
                 "attribution_persisted": True, "attribution_coverage_verified": True},
                {"candidate_hash": "b", "status": "confirmed", "submit_timestamp": "2026-10-08T10:00:00Z",
                 "attribution_persisted": False, "attribution_coverage_verified": False},
                {"candidate_hash": "c", "status": "immature", "submit_timestamp": "2026-10-08T11:50:00Z"},
            ]}), encoding="utf-8")
            candidates_path.write_text(json.dumps({"items": [
                {"candidateId": "a", "submit_timestamp": "2026-10-08T11:30:00Z",
                 "lifecycleStatus": "confirmed", "status": "ready_for_manual_review"},
                {"candidateId": "b", "submit_timestamp": "2026-10-08T10:00:00Z",
                 "lifecycleStatus": "confirmed", "status": "blocked",
                 "blockedReason": "blocked_unverified_round_attribution"},
                {"candidateId": "c", "submit_timestamp": "2026-10-08T11:50:00Z",
                 "lifecycleStatus": "immature", "status": "blocked", "blockedReason": "missing_share_data"},
                {"candidateId": "d", "submit_timestamp": "2026-10-07T10:00:00Z",
                 "lifecycleStatus": "confirmed", "status": "blocked",
                 "blockedReason": "blocked_unverified_round_attribution"},
                {"candidateId": "e", "submit_timestamp": "2026-10-08T11:50:00Z",
                 "lifecycleStatus": "confirmed", "status": "blocked",
                 "blockedReason": "blocked_unverified_round_attribution"},
            ]}), encoding="utf-8")
            payments_path.write_text(json.dumps({"items": [{"candidateHash": "d"}]}), encoding="utf-8")
            ledger_path.write_text(json.dumps({"candidate_hash": "d", "miningMode": "pool"}) + "\n",
                                   encoding="utf-8")

            health = resource_health.round_attribution_health(
                rounds_path, candidates_path, payments_path, ledger_path, now_epoch=now, recent_seconds=3600)
            self.assertEqual(health["historicalUnverifiableLedgerRecords"], 1)
            self.assertEqual(health["alreadyPaidButUnverifiedLedgerRecords"], 1)
            self.assertEqual(health["historicalUnresolvedUnverifiableCandidates"], 1)
            self.assertEqual(health["recentConfirmedMatureUnpaidMissingAttribution"], 1)
            self.assertEqual(health["recentNewlyFailedAttributions"][0]["reason"],
                             "blocked_unverified_round_attribution")
            self.assertTrue(health["latestRecentCompletedRoundPersisted"])
            self.assertEqual(health["maturityWaitCandidateCount"], 1)

    def test_pool_logrotate_shares_system_state_and_excludes_protected_ledgers(self):
        root = Path(__file__).resolve().parents[1]
        unit = (root / "ops/systemd/pepepow-pool-logrotate.service").read_text(encoding="utf-8")
        config = (root / "ops/systemd/pepepow-pool-runtime.logrotate").read_text(encoding="utf-8")
        self.assertIn("--state /var/lib/logrotate/status", unit)
        self.assertNotIn("logrotate-runtime.status", unit)
        self.assertNotIn("/var/lib/pepepow-pool/round-attribution.jsonl", config)
        self.assertNotIn("/var/lib/pepepow-pool/payment-actions.jsonl", config)
        self.assertNotIn("/var/lib/pepepow-pool/candidate-events.jsonl\n", config)
        self.assertNotIn("/var/lib/pepepow-pool/candidate-outcome-events.jsonl\n", config)

    def test_prior_durable_coverage_proof_remains_verified_without_new_digest_field(self):
        record = {
            "candidate_hash": "a" * 64,
            "previous_pool_boundary": "b" * 64,
            "total_share_count": 1,
            "total_share_score": 1.0,
            "wallet_count": 1,
            "worker_count": 1,
            "shares": {"wallet": {"share_count": 1, "share_score": 1.0}},
        }
        proof = {
            "status": "complete", "candidate_hash": "a" * 64,
            "previous_pool_boundary": "b" * 64,
            "segments_contiguous": True, "sequence_contiguous": True,
            "tail_truncated": False, "malformed_rows": 0,
            "source_first_sequence": 1, "source_last_sequence": 2,
            "attribution_sha256": resource_health.attribution_digest(record),
        }
        record["share_window_coverage"] = proof
        self.assertTrue(resource_health.record_has_coverage_proof(record))


if __name__ == "__main__":
    unittest.main()
