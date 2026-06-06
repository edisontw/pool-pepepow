#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path
import sys

# Insert ops/scripts to path to load payout_helper
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops" / "scripts"))
import payout_helper

class PayoutAccountingTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.accepted_path = self.tmp_path / "accepted-candidates.json"
        self.rounds_path = self.tmp_path / "rounds-snapshot.json"
        self.output_path = self.tmp_path / "payout-candidates.json"
        self.actions_log = self.tmp_path / "payment-actions.jsonl"
        self.snapshot_path = self.tmp_path / "payments-snapshot.json"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_payout_candidates_empty_missing_files(self):
        # Missing files should not crash and generate empty list
        rc = payout_helper.generate_payout_candidates(
            self.accepted_path, self.rounds_path, self.output_path
        )
        self.assertEqual(rc, 0)
        self.assertTrue(self.output_path.exists())

        with self.output_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data.get("items"), [])
        self.assertNotIn("candidates", data)

    def test_payout_candidates_blocking_states(self):
        # Create accepted candidates
        accepted_data = {
            "accepted_candidates": [
                {
                    "candidate_hash": "hash_confirmed_eligible",
                    "lifecycle_status": "confirmed",
                    "matched_height": 100,
                    "submit_timestamp": "2026-06-06T12:00:00Z"
                },
                {
                    "candidate_hash": "hash_confirmed_no_round",
                    "lifecycle_status": "confirmed",
                    "matched_height": 101,
                    "submit_timestamp": "2026-06-06T12:01:00Z"
                },
                {
                    "candidate_hash": "hash_confirmed_no_shares",
                    "lifecycle_status": "confirmed",
                    "matched_height": 102,
                    "submit_timestamp": "2026-06-06T12:02:00Z"
                },
                {
                    "candidate_hash": "hash_immature",
                    "lifecycle_status": "immature",
                    "matched_height": 103,
                    "submit_timestamp": "2026-06-06T12:03:00Z"
                },
                {
                    "candidate_hash": "hash_orphan",
                    "lifecycle_status": "orphan",
                    "matched_height": 104,
                    "submit_timestamp": "2026-06-06T12:04:00Z"
                },
                {
                    "candidate_hash": "hash_recorded",
                    "lifecycle_status": "candidate_recorded",
                    "matched_height": 105,
                    "submit_timestamp": "2026-06-06T12:05:00Z"
                }
            ]
        }
        with self.accepted_path.open("w", encoding="utf-8") as f:
            json.dump(accepted_data, f)

        # Create rounds snapshot
        rounds_data = {
            "rounds": [
                {
                    "candidate_hash": "hash_confirmed_eligible",
                    "shares": {
                        "walletA": {
                            "share_count": 10,
                            "share_score": 10.0,
                            "share_percent": 100.0
                        }
                    }
                },
                {
                    "candidate_hash": "hash_confirmed_no_shares",
                    # missing shares key
                }
            ]
        }
        with self.rounds_path.open("w", encoding="utf-8") as f:
            json.dump(rounds_data, f)

        rc = payout_helper.generate_payout_candidates(
            self.accepted_path, self.rounds_path, self.output_path
        )
        self.assertEqual(rc, 0)
        self.assertTrue(self.output_path.exists())

        with self.output_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        
        self.assertIn("items", data)
        self.assertNotIn("candidates", data)
        candidates = data.get("items", [])
        self.assertEqual(len(candidates), 6)

        cand_map = {c["candidate_hash"]: c for c in candidates}

        # 1. Eligible block
        c1 = cand_map["hash_confirmed_eligible"]
        self.assertEqual(c1["status"], "eligible")
        self.assertIsNone(c1["reason"])
        self.assertEqual(c1["shares"]["walletA"]["share_count"], 10)

        # 2. Confirmed block but missing round data
        c2 = cand_map["hash_confirmed_no_round"]
        self.assertEqual(c2["status"], "blocked")
        self.assertEqual(c2["reason"], "missing_round_data")

        # 3. Confirmed block but missing shares key
        c3 = cand_map["hash_confirmed_no_shares"]
        self.assertEqual(c3["status"], "blocked")
        self.assertEqual(c3["reason"], "missing_share_data")

        # 4. Immature block
        c4 = cand_map["hash_immature"]
        self.assertEqual(c4["status"], "blocked")
        self.assertEqual(c4["reason"], "immature_block")

        # 5. Orphan block
        c5 = cand_map["hash_orphan"]
        self.assertEqual(c5["status"], "blocked")
        self.assertEqual(c5["reason"], "orphan_block")

        # 6. Unconfirmed/recorded block
        c6 = cand_map["hash_recorded"]
        self.assertEqual(c6["status"], "blocked")
        self.assertEqual(c6["reason"], "unconfirmed_status_candidate_recorded")

    def test_record_payment_and_duplicate_handling(self):
        # Record first payment
        rc = payout_helper.record_payment(
            self.actions_log,
            self.snapshot_path,
            candidate_id="hasheligiblepayoutblock0001",
            wallet="PEPEPOW1WalletAddressTarget001",
            amount=500.25,
            txid="txidhash12345678901234567890"
        )
        self.assertEqual(rc, 0)
        self.assertTrue(self.actions_log.exists())
        self.assertTrue(self.snapshot_path.exists())

        # Verify snapshot data structure
        with self.snapshot_path.open("r", encoding="utf-8") as f:
            snapshot = json.load(f)
        self.assertEqual(len(snapshot["items"]), 1)
        item = snapshot["items"][0]
        self.assertEqual(item["wallet"], "PEPEPOW1WalletAddressTarget001")
        self.assertEqual(item["amount"], 500.25)
        self.assertEqual(item["txid"], "txidhash12345678901234567890")

        # Reject duplicate payment (same candidate_id + wallet)
        rc_dup = payout_helper.record_payment(
            self.actions_log,
            self.snapshot_path,
            candidate_id="hasheligiblepayoutblock0001",
            wallet="PEPEPOW1WalletAddressTarget001",
            amount=100.0,
            txid="txidhashdifferent9876543210"
        )
        self.assertEqual(rc_dup, 1)

        # Allow different wallet for same candidate_id
        rc_diff_wallet = payout_helper.record_payment(
            self.actions_log,
            self.snapshot_path,
            candidate_id="hasheligiblepayoutblock0001",
            wallet="PEPEPOW1WalletAddressTarget002",
            amount=200.0,
            txid="txidhashdifferent9876543210"
        )
        self.assertEqual(rc_diff_wallet, 0)

        # Allow same wallet for different candidate_id
        rc_diff_candidate = payout_helper.record_payment(
            self.actions_log,
            self.snapshot_path,
            candidate_id="hasheligiblepayoutblock0002",
            wallet="PEPEPOW1WalletAddressTarget001",
            amount=300.0,
            txid="txidhashdifferent7777777777"
        )
        self.assertEqual(rc_diff_candidate, 0)

        # Verify final snapshot content
        with self.snapshot_path.open("r", encoding="utf-8") as f:
            final_snapshot = json.load(f)
        items = final_snapshot["items"]
        self.assertEqual(len(items), 3)

        # Ensure correct properties and sorting descending by paidAt
        self.assertEqual(items[0]["wallet"], "PEPEPOW1WalletAddressTarget001")
        self.assertEqual(items[0]["amount"], 300.0)
        self.assertEqual(items[1]["wallet"], "PEPEPOW1WalletAddressTarget002")
        self.assertEqual(items[1]["amount"], 200.0)
        self.assertEqual(items[2]["wallet"], "PEPEPOW1WalletAddressTarget001")
        self.assertEqual(items[2]["amount"], 500.25)

    def test_record_payment_invalid_inputs(self):
        # Invalid candidate format
        self.assertEqual(payout_helper.record_payment(self.actions_log, self.snapshot_path, "invalid!!", "PEPEPOW1WalletAddressTarget001", 10.0, "txid123"), 1)
        # Invalid wallet format
        self.assertEqual(payout_helper.record_payment(self.actions_log, self.snapshot_path, "candidatehash123", "invalid wallet address!!", 10.0, "txid123"), 1)
        # Negative amount
        self.assertEqual(payout_helper.record_payment(self.actions_log, self.snapshot_path, "candidatehash123", "PEPEPOW1WalletAddressTarget001", -5.0, "txid123"), 1)

    def test_live_stratum_sh_commands_with_temp_runtime(self):
        import subprocess
        import os
        accepted_data = {
            "accepted_candidates": [
                {
                    "candidate_hash": "hashconfirmedeligibleblock0001",
                    "lifecycle_status": "confirmed",
                    "matched_height": 100,
                    "submit_timestamp": "2026-06-06T12:00:00Z"
                }
            ]
        }
        with self.accepted_path.open("w", encoding="utf-8") as f:
            json.dump(accepted_data, f)

        rounds_data = {
            "rounds": [
                {
                    "candidate_hash": "hashconfirmedeligibleblock0001",
                    "shares": {
                        "walletA": {
                            "share_count": 10,
                            "share_score": 10.0,
                            "share_percent": 100.0
                        }
                    }
                }
            ]
        }
        with self.rounds_path.open("w", encoding="utf-8") as f:
            json.dump(rounds_data, f)

        env = dict(os.environ)
        env["PEPEPOW_LIVE_STRATUM_RUNTIME_DIR"] = str(self.tmp_path)

        sh_path = Path(__file__).resolve().parents[1] / "ops" / "scripts" / "live-stratum.sh"
        res = subprocess.run(
            [str(sh_path), "payout-candidates"],
            env=env,
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0)
        self.assertTrue((self.tmp_path / "payout-candidates.json").exists())

        res_review = subprocess.run(
            [str(sh_path), "payout-review"],
            env=env,
            capture_output=True,
            text=True
        )
        self.assertEqual(res_review.returncode, 0)
        self.assertIn("hashconfirmedeligibleblock0001", res_review.stdout)
        self.assertIn("ELIGIBLE", res_review.stdout)

        # Test backward compatibility (old candidates format)
        payout_candidates_path = self.tmp_path / "payout-candidates.json"
        old_data = {
            "updated_at": "2026-06-06T12:00:00Z",
            "candidates": [
                {
                    "candidate_hash": "hasholdcompatblock0001",
                    "height": 99,
                    "lifecycle_status": "confirmed",
                    "status": "eligible",
                    "reason": None,
                    "shares": {}
                }
            ]
        }
        with payout_candidates_path.open("w", encoding="utf-8") as f:
            json.dump(old_data, f)
            
        res_review_compat = subprocess.run(
            [str(sh_path), "payout-review"],
            env=env,
            capture_output=True,
            text=True
        )
        self.assertEqual(res_review_compat.returncode, 0)
        self.assertIn("hasholdcompatblock0001", res_review_compat.stdout)
        
        # Regenerate to new format
        res = subprocess.run(
            [str(sh_path), "payout-candidates"],
            env=env,
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0)

        res_record = subprocess.run(
            [
                str(sh_path),
                "record-payment",
                "hashconfirmedeligibleblock0001",
                "PEPEPOW1WalletAddressTarget002",
                "150.0",
                "txidhash99999999999999999999"
            ],
            env=env,
            capture_output=True,
            text=True
        )
        self.assertEqual(res_record.returncode, 0)
        self.assertTrue((self.tmp_path / "payment-actions.jsonl").exists())
        self.assertTrue((self.tmp_path / "payments-snapshot.json").exists())

if __name__ == "__main__":
    unittest.main()
