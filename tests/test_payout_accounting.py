#!/usr/bin/env python3
import json
import tempfile
import unittest
import os
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
                    "submit_timestamp": "2026-06-06T12:00:00Z",
                    "reward": 50000.0
                },
                {
                    "candidate_hash": "hash_confirmed_no_round",
                    "lifecycle_status": "confirmed",
                    "matched_height": 101,
                    "submit_timestamp": "2026-06-06T12:01:00Z",
                    "reward": 50000.0
                },
                {
                    "candidate_hash": "hash_confirmed_no_shares",
                    "lifecycle_status": "confirmed",
                    "matched_height": 102,
                    "submit_timestamp": "2026-06-06T12:02:00Z",
                    "reward": 50000.0
                },
                {
                    "candidate_hash": "hash_immature",
                    "lifecycle_status": "immature",
                    "matched_height": 103,
                    "submit_timestamp": "2026-06-06T12:03:00Z",
                    "reward": 50000.0
                },
                {
                    "candidate_hash": "hash_orphan",
                    "lifecycle_status": "orphan",
                    "matched_height": 104,
                    "submit_timestamp": "2026-06-06T12:04:00Z",
                    "reward": 50000.0
                },
                {
                    "candidate_hash": "hash_recorded",
                    "lifecycle_status": "candidate_recorded",
                    "matched_height": 105,
                    "submit_timestamp": "2026-06-06T12:05:00Z",
                    "reward": 50000.0
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
                    "total_share_score": 10.0,
                    "total_share_count": 10,
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
                    "total_share_score": 0.0,
                    "total_share_count": 0
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
        self.assertEqual(c1["status"], "ready_for_manual_review")
        self.assertIsNone(c1["reason"])
        self.assertEqual(c1["shares"]["walletA"]["share_count"], 10)

        # 2. Confirmed block but missing round data
        c2 = cand_map["hash_confirmed_no_round"]
        self.assertEqual(c2["status"], "blocked")
        self.assertEqual(c2["reason"], "blocked_missing_round")

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


    def test_confirmed_candidate_not_orphan_from_round_status_fallback(self):
        accepted_data = {
            "accepted_candidates": [
                {
                    "candidate_hash": "hash_confirmed_round_status_orphan",
                    "lifecycle_status": "confirmed",
                    "matched_height": 4580896,
                    "reward": 50000.0,
                },
                {
                    "candidate_hash": "hash_confirmed_followup_no_match",
                    "lifecycle_status": "confirmed",
                    "followup_status": "no-match-found",
                    "matched_height": 4580897,
                    "reward": 50000.0,
                },
            ]
        }
        rounds_data = {
            "rounds": [
                {
                    "candidate_hash": "hash_confirmed_round_status_orphan",
                    "status": "orphan",
                    "total_share_score": 10.0,
                    "total_share_count": 10,
                    "shares": {"walletA": {"share_count": 10, "share_score": 10.0}},
                },
                {
                    "candidate_hash": "hash_confirmed_followup_no_match",
                    "total_share_score": 10.0,
                    "total_share_count": 10,
                    "shares": {"walletA": {"share_count": 10, "share_score": 10.0}},
                },
            ]
        }
        with self.accepted_path.open("w", encoding="utf-8") as f:
            json.dump(accepted_data, f)
        with self.rounds_path.open("w", encoding="utf-8") as f:
            json.dump(rounds_data, f)

        rc = payout_helper.generate_payout_candidates(
            self.accepted_path, self.rounds_path, self.output_path
        )
        self.assertEqual(rc, 0)

        with self.output_path.open("r", encoding="utf-8") as f:
            item_map = {item["candidate_hash"]: item for item in json.load(f).get("items", [])}

        confirmed = item_map["hash_confirmed_round_status_orphan"]
        self.assertEqual(confirmed["status"], "ready_for_manual_review")
        self.assertIsNone(confirmed["reason"])
        self.assertNotEqual(confirmed["blockedReason"], "orphan_block")

        no_match = item_map["hash_confirmed_followup_no_match"]
        self.assertEqual(no_match["status"], "blocked")
        self.assertEqual(no_match["reason"], "orphan_block")

    def test_confirmed_candidate_missing_reward_uses_missing_reward_reason(self):
        accepted_data = {
            "accepted_candidates": [
                {
                    "candidate_hash": "hash_confirmed_missing_reward",
                    "lifecycle_status": "confirmed",
                    "matched_height": 4580896,
                }
            ]
        }
        rounds_data = {
            "rounds": [
                {
                    "candidate_hash": "hash_confirmed_missing_reward",
                    "status": "orphan",
                    "total_share_score": 10.0,
                    "total_share_count": 10,
                    "shares": {"walletA": {"share_count": 10, "share_score": 10.0}},
                }
            ]
        }
        with self.accepted_path.open("w", encoding="utf-8") as f:
            json.dump(accepted_data, f)
        with self.rounds_path.open("w", encoding="utf-8") as f:
            json.dump(rounds_data, f)

        original_fetch = payout_helper.fetch_block_info_from_daemon
        payout_helper.fetch_block_info_from_daemon = lambda block_hash: (134, None)
        try:
            rc = payout_helper.generate_payout_candidates(
                self.accepted_path, self.rounds_path, self.output_path
            )
        finally:
            payout_helper.fetch_block_info_from_daemon = original_fetch
        self.assertEqual(rc, 0)

        with self.output_path.open("r", encoding="utf-8") as f:
            item = json.load(f)["items"][0]

        self.assertEqual(item["status"], "blocked")
        self.assertEqual(item["reason"], "blocked_missing_reward")
        self.assertNotEqual(item["blockedReason"], "orphan_block")

    def test_confirmed_candidate_with_shares_and_reward_creates_payouts_from_share_weights(self):
        accepted_data = {
            "accepted_candidates": [
                {
                    "candidate_hash": "hash_confirmed_reward_and_shares",
                    "lifecycle_status": "confirmed",
                    "matched_height": 4580896,
                    "reward": 1000.0,
                }
            ]
        }
        rounds_data = {
            "rounds": [
                {
                    "candidate_hash": "hash_confirmed_reward_and_shares",
                    "shares": {
                        "walletA": {"share_count": 2, "share_score": 2.0},
                        "walletB": {"share_count": 1, "share_score": 1.0},
                    },
                }
            ]
        }
        with self.accepted_path.open("w", encoding="utf-8") as f:
            json.dump(accepted_data, f)
        with self.rounds_path.open("w", encoding="utf-8") as f:
            json.dump(rounds_data, f)

        old_min = os.environ.get("PEPEPOW_MIN_PAYOUT")
        os.environ["PEPEPOW_MIN_PAYOUT"] = "1"
        try:
            rc = payout_helper.generate_payout_candidates(
                self.accepted_path, self.rounds_path, self.output_path
            )
        finally:
            if old_min is None:
                os.environ.pop("PEPEPOW_MIN_PAYOUT", None)
            else:
                os.environ["PEPEPOW_MIN_PAYOUT"] = old_min
        self.assertEqual(rc, 0)

        with self.output_path.open("r", encoding="utf-8") as f:
            item = json.load(f)["items"][0]

        self.assertEqual(item["status"], "ready_for_manual_review")
        self.assertIsNone(item["reason"])
        self.assertEqual(item["weightMode"], "share_difficulty_sum")
        self.assertEqual(item["roundShareTotal"], 3.0)
        self.assertEqual(len(item["payouts"]), 2)
        self.assertTrue(all(p["status"] == "pending_manual_payment" for p in item["payouts"]))

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
                    "submit_timestamp": "2026-06-06T12:00:00Z",
                    "reward": 50000.0
                }
            ]
        }
        with self.accepted_path.open("w", encoding="utf-8") as f:
            json.dump(accepted_data, f)

        rounds_data = {
            "rounds": [
                {
                    "candidate_hash": "hashconfirmedeligibleblock0001",
                    "total_share_score": 10.0,
                    "total_share_count": 10,
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
        self.assertIn("READY_FOR_MANUAL_REVIEW", res_review.stdout)

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
        self.assertIn("ELIGIBLE", res_review_compat.stdout)
        
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

    def test_payout_candidates_harden_rules(self):
        # 1. Missing reward
        accepted_data = {
            "accepted_candidates": [
                {
                    "candidate_hash": "cand_missing_reward",
                    "lifecycle_status": "confirmed",
                    "matched_height": 200,
                    "submit_timestamp": "2026-06-06T12:00:00Z"
                    # missing reward field
                },
                {
                    "candidate_hash": "cand_zero_reward",
                    "lifecycle_status": "confirmed",
                    "matched_height": 201,
                    "submit_timestamp": "2026-06-06T12:01:00Z",
                    "reward": 0.0
                },
                {
                    "candidate_hash": "cand_synthetic_reward",
                    "lifecycle_status": "confirmed",
                    "matched_height": 202,
                    "submit_timestamp": "2026-06-06T12:02:00Z",
                    "reward": "synthetic"
                },
                {
                    "candidate_hash": "cand_zero_weight",
                    "lifecycle_status": "confirmed",
                    "matched_height": 203,
                    "submit_timestamp": "2026-06-06T12:03:00Z",
                    "reward": 50000.0
                }
            ]
        }
        with self.accepted_path.open("w", encoding="utf-8") as f:
            json.dump(accepted_data, f)

        rounds_data = {
            "rounds": [
                {
                    "candidate_hash": "cand_missing_reward",
                    "total_share_score": 10.0,
                    "total_share_count": 10,
                    "shares": {"walletA": {"share_count": 10}}
                },
                {
                    "candidate_hash": "cand_zero_reward",
                    "total_share_score": 10.0,
                    "total_share_count": 10,
                    "shares": {"walletA": {"share_count": 10}}
                },
                {
                    "candidate_hash": "cand_synthetic_reward",
                    "total_share_score": 10.0,
                    "total_share_count": 10,
                    "shares": {"walletA": {"share_count": 10}}
                },
                {
                    "candidate_hash": "cand_zero_weight",
                    "total_share_score": 0.0,
                    "total_share_count": 0,
                    "shares": {"walletA": {"share_count": 0}}
                }
            ]
        }
        with self.rounds_path.open("w", encoding="utf-8") as f:
            json.dump(rounds_data, f)

        rc = payout_helper.generate_payout_candidates(
            self.accepted_path, self.rounds_path, self.output_path
        )
        self.assertEqual(rc, 0)

        with self.output_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        items = data.get("items", [])
        self.assertEqual(len(items), 4)
        item_map = {item["candidate_hash"]: item for item in items}

        self.assertEqual(item_map["cand_missing_reward"]["status"], "blocked")
        self.assertEqual(item_map["cand_missing_reward"]["reason"], "blocked_missing_reward")

        self.assertEqual(item_map["cand_zero_reward"]["status"], "blocked")
        self.assertEqual(item_map["cand_zero_reward"]["reason"], "blocked_zero_reward")

        self.assertEqual(item_map["cand_synthetic_reward"]["status"], "blocked")
        self.assertEqual(item_map["cand_synthetic_reward"]["reason"], "blocked_invalid_reward")

        self.assertEqual(item_map["cand_zero_weight"]["status"], "blocked")
        self.assertEqual(item_map["cand_zero_weight"]["reason"], "blocked_zero_weight")

        # Test pool-snapshot.json reward lookup via environment variable
        import os
        pool_snapshot_path = self.tmp_path / "pool-snapshot.json"
        pool_snapshot_data = {
            "blocks": [
                {
                    "hash": "cand_resolved_via_snapshot",
                    "height": 300,
                    "reward": 60000.0,
                    "status": "observed-network",
                    "confirmations": 101
                }
            ]
        }
        with pool_snapshot_path.open("w", encoding="utf-8") as f:
            json.dump(pool_snapshot_data, f)

        # Set env variable
        os.environ["PEPEPOW_POOL_CORE_SNAPSHOT_OUTPUT"] = str(pool_snapshot_path)

        accepted_data_snap = {
            "accepted_candidates": [
                {
                    "candidate_hash": "cand_resolved_via_snapshot",
                    "lifecycle_status": "confirmed",
                    "matched_height": 300,
                    "submit_timestamp": "2026-06-06T12:00:00Z"
                    # no reward here, should be resolved from pool-snapshot.json
                }
            ]
        }
        with self.accepted_path.open("w", encoding="utf-8") as f:
            json.dump(accepted_data_snap, f)

        rounds_data_snap = {
            "rounds": [
                {
                    "candidate_hash": "cand_resolved_via_snapshot",
                    "total_share_score": 10.0,
                    "total_share_count": 10,
                    "shares": {
                        "walletB": {
                            "share_count": 10,
                            "share_score": 10.0,
                            "share_percent": 100.0
                        }
                    }
                }
            ]
        }
        with self.rounds_path.open("w", encoding="utf-8") as f:
            json.dump(rounds_data_snap, f)

        rc = payout_helper.generate_payout_candidates(
            self.accepted_path, self.rounds_path, self.output_path
        )
        self.assertEqual(rc, 0)

        with self.output_path.open("r", encoding="utf-8") as f:
            res_data = json.load(f)

        items_snap = res_data.get("items", [])
        self.assertEqual(len(items_snap), 1)
        item = items_snap[0]
        self.assertEqual(item["status"], "ready_for_manual_review")
        self.assertEqual(item["grossReward"], 60000.0)
        self.assertEqual(item["rewardSource"], "pool-snapshot")
        self.assertIsNone(item["reason"])

        # Test null reward rejection
        pool_snapshot_data_null = {
            "blocks": [
                {
                    "hash": "cand_resolved_via_snapshot",
                    "height": 300,
                    "reward": None,
                    "status": "observed-network",
                    "confirmations": 101
                }
            ]
        }
        with pool_snapshot_path.open("w", encoding="utf-8") as f:
            json.dump(pool_snapshot_data_null, f)

        rc = payout_helper.generate_payout_candidates(
            self.accepted_path, self.rounds_path, self.output_path
        )
        self.assertEqual(rc, 0)

        with self.output_path.open("r", encoding="utf-8") as f:
            res_data_null = json.load(f)
        item_null = res_data_null.get("items", [])[0]
        self.assertEqual(item_null["status"], "blocked")
        self.assertEqual(item_null["reason"], "blocked_missing_reward")
        self.assertIsNone(item_null["grossReward"])

        # Clean up env
        os.environ.pop("PEPEPOW_POOL_CORE_SNAPSHOT_OUTPUT", None)

    def test_payout_candidates_daemon_rpc_fallback_and_orphan(self):
        # Mock payout_helper.query_rpc
        original_query_rpc = payout_helper.query_rpc
        
        rpc_calls = []
        def mock_query_rpc(method, params):
            rpc_calls.append((method, params))
            # Mock getblock
            if method == "getblock":
                block_hash = params[0]
                if block_hash == "hash_resolved_via_daemon_rpc":
                    return {
                        "confirmations": 12,
                        "tx": ["coinbase_tx_hash_123"]
                    }
                elif block_hash == "hash_orphan_via_daemon_rpc":
                    return {
                        "confirmations": -1,
                        "tx": ["coinbase_tx_hash_456"]
                    }
            # Mock getrawtransaction
            elif method == "getrawtransaction":
                txid = params[0]
                if txid == "coinbase_tx_hash_123":
                    return {
                        "vout": [
                            {"value": 3500.0},
                            {"value": 3500.0}
                        ]
                    }
                elif txid == "coinbase_tx_hash_456":
                    return {
                        "vout": [
                            {"value": 7000.0}
                        ]
                    }
            return None

        payout_helper.query_rpc = mock_query_rpc
        
        try:
            accepted_data = {
                "accepted_candidates": [
                    {
                        "candidate_hash": "hash_resolved_via_daemon_rpc",
                        "lifecycle_status": "confirmed",
                        "matched_height": 500,
                        "submit_timestamp": "2026-06-06T12:00:00Z"
                        # No reward field -> triggers daemon RPC fallback
                    },
                    {
                        "candidate_hash": "hash_orphan_via_daemon_rpc",
                        "lifecycle_status": "confirmed",
                        "matched_height": 501,
                        "submit_timestamp": "2026-06-06T12:01:00Z"
                        # Confirmed in accepted candidate, but orphan on-chain
                    },
                    {
                        "candidate_hash": "hash_orphan_via_rounds_snapshot",
                        "lifecycle_status": "confirmed",
                        "matched_height": 502,
                        "submit_timestamp": "2026-06-06T12:02:00Z",
                        "reward": 7000.0
                    }
                ]
            }
            with self.accepted_path.open("w", encoding="utf-8") as f:
                json.dump(accepted_data, f)

            rounds_data = {
                "rounds": [
                    {
                        "candidate_hash": "hash_resolved_via_daemon_rpc",
                        "total_share_score": 10.0,
                        "total_share_count": 10,
                        "shares": {
                            "walletA": {
                                "share_count": 10,
                                "share_score": 10.0,
                                "share_percent": 100.0
                            }
                        }
                    },
                    {
                        "candidate_hash": "hash_orphan_via_daemon_rpc",
                        "total_share_score": 10.0,
                        "total_share_count": 10,
                        "shares": {
                            "walletA": {
                                "share_count": 10,
                                "share_score": 10.0,
                                "share_percent": 100.0
                            }
                        }
                    },
                    {
                        "candidate_hash": "hash_orphan_via_rounds_snapshot",
                        "status": "orphan",  # Marked as orphan in rounds snapshot
                        "total_share_score": 10.0,
                        "total_share_count": 10,
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

            rc = payout_helper.generate_payout_candidates(
                self.accepted_path, self.rounds_path, self.output_path
            )
            self.assertEqual(rc, 0)

            with self.output_path.open("r", encoding="utf-8") as f:
                data = json.load(f)

            items = data.get("items", [])
            self.assertEqual(len(items), 3)
            item_map = {item["candidate_hash"]: item for item in items}

            # 1. Block resolved via daemon RPC
            c1 = item_map["hash_resolved_via_daemon_rpc"]
            self.assertEqual(c1["status"], "ready_for_manual_review")
            self.assertEqual(c1["grossReward"], 7000.0)
            self.assertEqual(c1["rewardSource"], "daemon-rpc")
            self.assertIsNone(c1["reason"])

            # 2. Confirmed lifecycle candidates are not marked orphan from daemon confirmations alone.
            c2 = item_map["hash_orphan_via_daemon_rpc"]
            self.assertEqual(c2["status"], "ready_for_manual_review")
            self.assertIsNone(c2["reason"])

            # 3. Confirmed lifecycle candidates are not marked orphan from rounds snapshot status alone.
            c3 = item_map["hash_orphan_via_rounds_snapshot"]
            self.assertEqual(c3["status"], "ready_for_manual_review")
            self.assertIsNone(c3["reason"])

        finally:
            payout_helper.query_rpc = original_query_rpc

    def test_payout_candidates_already_paid(self):
        accepted_data = {
            "accepted_candidates": [
                {
                    "candidate_hash": "hash_already_paid",
                    "lifecycle_status": "confirmed",
                    "matched_height": 600,
                    "submit_timestamp": "2026-06-06T12:00:00Z",
                    "reward": 5000.0
                }
            ]
        }
        with self.accepted_path.open("w", encoding="utf-8") as f:
            json.dump(accepted_data, f)

        rounds_data = {
            "rounds": [
                {
                    "candidate_hash": "hash_already_paid",
                    "total_share_score": 10.0,
                    "total_share_count": 10,
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

        # Write to payment-actions.jsonl (relative to self.output_path)
        actions_log_path = self.output_path.parent / "payment-actions.jsonl"
        with actions_log_path.open("w", encoding="utf-8") as f:
            f.write(json.dumps({
                "candidate_id": "hash_already_paid",
                "wallet": "walletA",
                "amount": 4950.0,
                "txid": "txid_already_paid_123"
            }) + "\n")

        rc = payout_helper.generate_payout_candidates(
            self.accepted_path, self.rounds_path, self.output_path
        )
        self.assertEqual(rc, 0)

        with self.output_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        items = data.get("items", [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["status"], "blocked")
        self.assertEqual(items[0]["reason"], "blocked_already_paid")

    def test_generate_payments_snapshot_includes_metadata_when_available(self):
        # Create a mock payout-candidates.json containing a candidate
        candidates_data = {
            "items": [
                {
                    "candidate_hash": "hashconfirmedeligibleblock9999",
                    "height": 4573193,
                    "blockHash": "hashconfirmedeligibleblock9999",
                    "status": "ready_for_manual_review"
                }
            ]
        }
        with (self.tmp_path / "payout-candidates.json").open("w", encoding="utf-8") as f:
            json.dump(candidates_data, f)

        # Record a payment
        rc = payout_helper.record_payment(
            self.actions_log,
            self.snapshot_path,
            candidate_id="hashconfirmedeligibleblock9999",
            wallet="PEPEPOW1WalletAddressTarget001",
            amount=500.25,
            txid="txidhash12345678901234567890"
        )
        self.assertEqual(rc, 0)

        # Verify payments snapshot contains metadata
        with self.snapshot_path.open("r", encoding="utf-8") as f:
            snapshot = json.load(f)
        self.assertEqual(len(snapshot["items"]), 1)
        item = snapshot["items"][0]
        self.assertEqual(item["wallet"], "PEPEPOW1WalletAddressTarget001")
        self.assertEqual(item["amount"], 500.25)
        self.assertEqual(item["txid"], "txidhash12345678901234567890")
        self.assertEqual(item["candidateHash"], "hashconfirmedeligibleblock9999")
        self.assertEqual(item["blockHash"], "hashconfirmedeligibleblock9999")
        self.assertEqual(item["blockHeight"], 4573193)
        self.assertEqual(item["status"], "ready_for_manual_review")

    def test_generate_payments_snapshot_old_payment_actions_without_metadata_work(self):
        # Record a payment for a candidate that doesn't exist in payout-candidates.json (which is absent)
        rc = payout_helper.record_payment(
            self.actions_log,
            self.snapshot_path,
            candidate_id="hashabsenteligibleblock9999",
            wallet="PEPEPOW1WalletAddressTarget001",
            amount=500.25,
            txid="txidhash12345678901234567890"
        )
        self.assertEqual(rc, 0)

        # Verify payments snapshot does not have metadata but still generated correctly without crash
        with self.snapshot_path.open("r", encoding="utf-8") as f:
            snapshot = json.load(f)
        self.assertEqual(len(snapshot["items"]), 1)
        item = snapshot["items"][0]
        self.assertEqual(item["wallet"], "PEPEPOW1WalletAddressTarget001")
        self.assertEqual(item["amount"], 500.25)
        self.assertEqual(item["txid"], "txidhash12345678901234567890")
        self.assertNotIn("candidateHash", item)
        self.assertNotIn("blockHash", item)
        self.assertNotIn("blockHeight", item)
        self.assertNotIn("status", item)

    def test_rebuild_payments_snapshot_command(self):
        # Create a mock payout-candidates.json containing a candidate
        candidates_data = {
            "items": [
                {
                    "candidate_hash": "hashconfirmedeligibleblock9999",
                    "height": 4573193,
                    "blockHash": "hashconfirmedeligibleblock9999",
                    "status": "ready_for_manual_review"
                }
            ]
        }
        with (self.tmp_path / "payout-candidates.json").open("w", encoding="utf-8") as f:
            json.dump(candidates_data, f)

        # Create manual actions log entries
        with self.actions_log.open("w", encoding="utf-8") as f:
            f.write(json.dumps({
                "candidate_id": "hashconfirmedeligibleblock9999",
                "wallet": "PEPEPOW1WalletAddressTarget001",
                "amount": 500.25,
                "txid": "txidhash12345678901234567890",
                "timestamp": "2026-06-06T15:00:00Z"
            }) + "\n")

        # Invoke rebuild subcommand via main
        sys_argv_backup = sys.argv
        try:
            sys.argv = [
                "payout_helper.py",
                "rebuild-payments-snapshot",
                "--actions-log", str(self.actions_log),
                "--snapshot", str(self.snapshot_path)
            ]
            rc = payout_helper.main()
            self.assertEqual(rc, 0)
        finally:
            sys.argv = sys_argv_backup

        # Verify payments snapshot contains metadata
        with self.snapshot_path.open("r", encoding="utf-8") as f:
            snapshot = json.load(f)
        self.assertEqual(len(snapshot["items"]), 1)
        item = snapshot["items"][0]
        self.assertEqual(item["wallet"], "PEPEPOW1WalletAddressTarget001")
        self.assertEqual(item["candidateHash"], "hashconfirmedeligibleblock9999")
        self.assertEqual(item["blockHeight"], 4573193)
        self.assertEqual(item["status"], "ready_for_manual_review")

    def test_refresh_payment_confirmations(self):
        # 1. Setup mock pool-snapshot.json to provide current Height
        pool_snap_path = self.tmp_path / "pool-snapshot.json"
        pool_snap_data = {
            "network": {
                "height": 4577623
            }
        }
        with pool_snap_path.open("w", encoding="utf-8") as f:
            json.dump(pool_snap_data, f)
        
        # Set environment variable so payout_helper loads this mock snapshot
        import os
        os.environ["PEPEPOW_POOL_CORE_SNAPSHOT_OUTPUT"] = str(pool_snap_path)
        
        try:
            # Create a mock payout-candidates.json containing candidate height info
            candidates_data = {
                "items": [
                    {
                        "candidate_hash": "hashconfirmedeligibleblock9999",
                        "height": 4573193,
                        "blockHash": "hashconfirmedeligibleblock9999",
                        "status": "ready_for_manual_review"
                    }
                ]
            }
            with (self.tmp_path / "payout-candidates.json").open("w", encoding="utf-8") as f:
                json.dump(candidates_data, f)

            # Create manual actions log entries
            with self.actions_log.open("w", encoding="utf-8") as f:
                f.write(json.dumps({
                    "candidate_id": "hashconfirmedeligibleblock9999",
                    "wallet": "PEPEPOW1WalletAddressTarget001",
                    "amount": 500.25,
                    "txid": "txidhash12345678901234567890",
                    "timestamp": "2026-06-06T15:00:00Z"
                }) + "\n")

            # First run rebuild to generate the initial snapshot (with confirmations = 1 since current Height is loaded)
            sys_argv_backup = sys.argv
            try:
                sys.argv = [
                    "payout_helper.py",
                    "rebuild-payments-snapshot",
                    "--actions-log", str(self.actions_log),
                    "--snapshot", str(self.snapshot_path)
                ]
                rc = payout_helper.main()
                self.assertEqual(rc, 0)
            finally:
                sys.argv = sys_argv_backup

            # Confirmations should be max(0, currentHeight - blockHeight + 1)
            # max(0, 4577623 - 4573193 + 1) = 4431
            with self.snapshot_path.open("r", encoding="utf-8") as f:
                snapshot = json.load(f)
            self.assertEqual(snapshot["items"][0]["confirmations"], 4431)
            self.assertEqual(snapshot["items"][0]["candidateHash"], "hashconfirmedeligibleblock9999")
            self.assertEqual(snapshot["items"][0]["status"], "ready_for_manual_review")

            # 2. Test refresh command preserving existing properties but recomputing confirmations on new height
            pool_snap_data["network"]["height"] = 4577630
            with pool_snap_path.open("w", encoding="utf-8") as f:
                json.dump(pool_snap_data, f)

            sys_argv_backup = sys.argv
            try:
                sys.argv = [
                    "payout_helper.py",
                    "refresh-payment-confirmations",
                    "--actions-log", str(self.actions_log),
                    "--snapshot", str(self.snapshot_path)
                ]
                rc = payout_helper.main()
                self.assertEqual(rc, 0)
            finally:
                sys.argv = sys_argv_backup

            # Confirmations should now be max(0, 4577630 - 4573193 + 1) = 4438
            with self.snapshot_path.open("r", encoding="utf-8") as f:
                snapshot = json.load(f)
            item = snapshot["items"][0]
            self.assertEqual(item["confirmations"], 4438)
            # Preserves other attributes
            self.assertEqual(item["wallet"], "PEPEPOW1WalletAddressTarget001")
            self.assertEqual(item["amount"], 500.25)
            self.assertEqual(item["txid"], "txidhash12345678901234567890")
            self.assertEqual(item["candidateHash"], "hashconfirmedeligibleblock9999")
            self.assertEqual(item["blockHash"], "hashconfirmedeligibleblock9999")
            self.assertEqual(item["blockHeight"], 4573193)
            self.assertEqual(item["status"], "ready_for_manual_review")

            # 3. Test missing blockHeight preserves safe fallback and doesn't crash
            # We will create an action with no metadata in candidates map, and no existing metadata in snapshot
            with self.actions_log.open("w", encoding="utf-8") as f:
                f.write(json.dumps({
                    "candidate_id": "missing_metadata_hash",
                    "wallet": "PEPEPOW1WalletAddressTarget001",
                    "amount": 100.0,
                    "txid": "txidhash99999999999999999999",
                    "timestamp": "2026-06-06T15:00:00Z"
                }) + "\n")
            
            # Remove candidates and snapshot file to test pure missing case
            if self.snapshot_path.exists():
                self.snapshot_path.unlink()
            
            sys_argv_backup = sys.argv
            try:
                sys.argv = [
                    "payout_helper.py",
                    "refresh-payment-confirmations",
                    "--actions-log", str(self.actions_log),
                    "--snapshot", str(self.snapshot_path)
                ]
                rc = payout_helper.main()
                self.assertEqual(rc, 0)
            finally:
                sys.argv = sys_argv_backup

            with self.snapshot_path.open("r", encoding="utf-8") as f:
                snapshot = json.load(f)
            self.assertEqual(snapshot["items"][0]["confirmations"], 1) # Fallback to default 1
            self.assertNotIn("blockHeight", snapshot["items"][0])

        finally:
            os.environ.pop("PEPEPOW_POOL_CORE_SNAPSHOT_OUTPUT", None)

    def test_build_carry_snapshot_behavior(self):
        # Setup inputs
        candidates_file = self.tmp_path / "test-payout-candidates.json"
        carry_snapshot_file = self.tmp_path / "payout-carry-snapshot.json"
        
        candidates_data = {
            "updated_at": "2026-06-06T12:00:00Z",
            "items": [
                {
                    "candidateId": "height-100",
                    "blockHash": "hash100",
                    "height": 100,
                    "lifecycleStatus": "confirmed",
                    "status": "ready_for_manual_review",
                    "payouts": [
                        {
                            "wallet": "wallet_below1",
                            "amount": 10.0,
                            "status": "below_threshold"
                        },
                        {
                            "wallet": "wallet_below2",
                            "amount": 20.0,
                            "status": "below_threshold_carried"
                        },
                        {
                            "wallet": "wallet_ready",
                            "amount": 150000.0,
                            "status": "ready_for_manual_review"
                        }
                    ]
                },
                {
                    "candidateId": "height-101",
                    "blockHash": "hash101",
                    "height": 101,
                    "lifecycleStatus": "immature",
                    "status": "blocked",
                    "reason": "immature_block",
                    "payouts": [
                        {
                            "wallet": "wallet_immature",
                            "amount": 150.0,
                            "status": "blocked_immature"
                        }
                    ]
                },
                {
                    "candidateId": "height-102",
                    "blockHash": "hash102",
                    "height": 102,
                    "lifecycleStatus": "orphan",
                    "status": "blocked",
                    "reason": "orphan_block",
                    "payouts": [
                        {
                            "wallet": "wallet_orphan",
                            "amount": 150.0,
                            "status": "blocked_orphan"
                        }
                    ]
                },
                {
                    "candidateId": "height-100",
                    "blockHash": "hash100",
                    "height": 100,
                    "lifecycleStatus": "confirmed",
                    "status": "ready_for_manual_review",
                    "payouts": [
                        {
                            "wallet": "wallet_below1",
                            "amount": 10.0,
                            "status": "below_threshold"
                        }
                    ]
                }
            ]
        }
        
        with candidates_file.open("w", encoding="utf-8") as f:
            json.dump(candidates_data, f)
            
        # Execute carry builder
        rc = payout_helper.generate_carry_snapshot(candidates_file, carry_snapshot_file)
        self.assertEqual(rc, 0)
        self.assertTrue(carry_snapshot_file.exists())
        
        with carry_snapshot_file.open("r", encoding="utf-8") as f:
            snapshot = json.load(f)
            
        self.assertIn("generatedAt", snapshot)
        items = snapshot.get("items", [])
        
        # We expect exactly 2 items: wallet_below1 (deduplicated) and wallet_below2
        self.assertEqual(len(items), 2)
        
        item1 = items[0]
        self.assertEqual(item1["wallet"], "wallet_below1")
        self.assertEqual(item1["amount"], 10.0)
        self.assertEqual(item1["sourceCandidateId"], "height-100")
        self.assertEqual(item1["sourceBlockHeight"], 100)
        self.assertEqual(item1["sourceBlockHash"], "hash100")
        self.assertEqual(item1["status"], "below_threshold_carried")
        
        item2 = items[1]
        self.assertEqual(item2["wallet"], "wallet_below2")
        self.assertEqual(item2["amount"], 20.0)
        self.assertEqual(item2["sourceCandidateId"], "height-100")
        self.assertEqual(item2["sourceBlockHeight"], 100)
        self.assertEqual(item2["sourceBlockHash"], "hash100")
        self.assertEqual(item2["status"], "below_threshold_carried")
        
        # Test missing file produces empty items safely
        missing_file = self.tmp_path / "nonexistent-candidates.json"
        rc_missing = payout_helper.generate_carry_snapshot(missing_file, carry_snapshot_file)
        self.assertEqual(rc_missing, 0)
        with carry_snapshot_file.open("r", encoding="utf-8") as f:
            snap_missing = json.load(f)
        self.assertEqual(snap_missing.get("items"), [])
        
        # Test malformed JSON file produces empty items safely
        malformed_file = self.tmp_path / "malformed-candidates.json"
        with malformed_file.open("w", encoding="utf-8") as f:
            f.write("{invalid_json}")
        rc_malformed = payout_helper.generate_carry_snapshot(malformed_file, carry_snapshot_file)
        self.assertEqual(rc_malformed, 0)
        with carry_snapshot_file.open("r", encoding="utf-8") as f:
            snap_malformed = json.load(f)
        self.assertEqual(snap_malformed.get("items"), [])

        # Test CLI main invocation works
        sys_argv_backup = sys.argv
        try:
            sys.argv = [
                "payout_helper.py",
                "build-carry-snapshot",
                "--candidates", str(candidates_file),
                "--snapshot", str(carry_snapshot_file)
            ]
            rc_main = payout_helper.main()
            self.assertEqual(rc_main, 0)
        finally:
            sys.argv = sys_argv_backup
            
        with carry_snapshot_file.open("r", encoding="utf-8") as f:
            snap_main = json.load(f)
        self.assertEqual(len(snap_main.get("items", [])), 2)

    def test_candidate_generator_consumes_carry(self):
        import os
        # Set min payout env var
        os.environ["PEPEPOW_MIN_PAYOUT"] = "100.0"
        
        try:
            # Setup carry snapshot file
            carry_path = self.tmp_path / "payout-carry-snapshot.json"
            carry_data = {
                "generatedAt": "2026-06-06T12:00:00Z",
                "items": [
                    {
                        "wallet": "walletA",
                        "amount": 40.0,
                        "sourceCandidateId": "height-99",
                        "sourceBlockHeight": 99,
                        "sourceBlockHash": "hash99",
                        "status": "below_threshold_carried"
                    },
                    {
                        "wallet": "walletA",
                        "amount": 20.0,
                        "sourceCandidateId": "height-98",
                        "sourceBlockHeight": 98,
                        "sourceBlockHash": "hash98",
                        "status": "below_threshold_carried"
                    },
                    {
                        "wallet": "walletC", # Other wallet
                        "amount": 150.0,
                        "sourceCandidateId": "height-99",
                        "sourceBlockHeight": 99,
                        "sourceBlockHash": "hash99",
                        "status": "below_threshold_carried"
                    }
                ]
            }
            with carry_path.open("w", encoding="utf-8") as f:
                json.dump(carry_data, f)
                
            # Setup accepted candidates and rounds snapshots
            accepted_data = {
                "accepted_candidates": [
                    {
                        "candidate_hash": "hash_immature_block",
                        "lifecycle_status": "immature",
                        "matched_height": 100,
                        "submit_timestamp": "2026-06-06T12:00:00Z",
                        "reward": 500.0
                    },
                    {
                        "candidate_hash": "hash_eligible_1",
                        "lifecycle_status": "confirmed",
                        "matched_height": 101,
                        "submit_timestamp": "2026-06-06T12:01:00Z",
                        "reward": 50.0 # base net reward ~ 49.5 for A (50% share) and B (50% share)
                    },
                    {
                        "candidate_hash": "hash_eligible_2",
                        "lifecycle_status": "confirmed",
                        "matched_height": 102,
                        "submit_timestamp": "2026-06-06T12:02:00Z",
                        "reward": 50.0
                    }
                ]
            }
            with self.accepted_path.open("w", encoding="utf-8") as f:
                json.dump(accepted_data, f)
                
            rounds_data = {
                "rounds": [
                    {
                        "candidate_hash": "hash_immature_block",
                        "total_share_score": 10.0,
                        "total_share_count": 10,
                        "shares": {
                            "walletA": {
                                "share_count": 10,
                                "share_score": 10.0,
                                "share_percent": 100.0
                            }
                        }
                    },
                    {
                        "candidate_hash": "hash_eligible_1",
                        "total_share_score": 20.0,
                        "total_share_count": 20,
                        "shares": {
                            "walletA": {
                                "share_count": 10,
                                "share_score": 10.0,
                                "share_percent": 50.0
                            },
                            "walletB": {
                                "share_count": 10,
                                "share_score": 10.0,
                                "share_percent": 50.0
                            }
                        }
                    },
                    {
                        "candidate_hash": "hash_eligible_2",
                        "total_share_score": 20.0,
                        "total_share_count": 20,
                        "shares": {
                            "walletA": {
                                "share_count": 10,
                                "share_score": 10.0,
                                "share_percent": 50.0
                            },
                            "walletB": {
                                "share_count": 10,
                                "share_score": 10.0,
                                "share_percent": 50.0
                            }
                        }
                    }
                ]
            }
            with self.rounds_path.open("w", encoding="utf-8") as f:
                json.dump(rounds_data, f)
                
            # Run candidates generator
            rc = payout_helper.generate_payout_candidates(
                self.accepted_path, self.rounds_path, self.output_path, carry_path
            )
            self.assertEqual(rc, 0)
            
            with self.output_path.open("r", encoding="utf-8") as f:
                output = json.load(f)
                
            items = {item["candidate_hash"]: item for item in output.get("items", [])}
            
            # 1. Verify immature block does not consume carry and has no payouts
            c_immature = items["hash_immature_block"]
            self.assertEqual(c_immature["status"], "blocked")
            self.assertEqual(c_immature["payouts"], [])
            
            # 2. Verify hash_eligible_1 consumes walletA carry (40.0 + 20.0 = 60.0)
            c_el1 = items["hash_eligible_1"]
            payouts_el1 = {p["wallet"]: p for p in c_el1["payouts"]}
            
            # walletA: net share = 50 * 0.99 * 0.5 = 24.75. carry = 60.0. total = 84.75 < 100.0 (min_payout)
            # So status is below_threshold_carried
            p_a1 = payouts_el1["walletA"]
            self.assertAlmostEqual(p_a1["baseAmount"], 24.75)
            self.assertAlmostEqual(p_a1["carryInAmount"], 60.0)
            self.assertAlmostEqual(p_a1["amount"], 84.75)
            self.assertEqual(p_a1["status"], "below_threshold_carried")
            self.assertEqual(p_a1["carrySourceCount"], 2)
            self.assertIn("height-99", p_a1["carrySourceCandidateIds"])
            self.assertIn("height-98", p_a1["carrySourceCandidateIds"])
            
            # walletB: net share = 24.75. no carry. total = 24.75 < 100.0.
            # So status is below_threshold_carried
            p_b1 = payouts_el1["walletB"]
            self.assertAlmostEqual(p_b1["baseAmount"], 24.75)
            self.assertAlmostEqual(p_b1["carryInAmount"], 0.0)
            self.assertEqual(p_b1["status"], "below_threshold_carried")
            
            # 3. Verify hash_eligible_2 does NOT consume walletA carry again (since it was consumed in hash_eligible_1)
            c_el2 = items["hash_eligible_2"]
            payouts_el2 = {p["wallet"]: p for p in c_el2["payouts"]}
            
            p_a2 = payouts_el2["walletA"]
            self.assertAlmostEqual(p_a2["baseAmount"], 24.75)
            self.assertAlmostEqual(p_a2["carryInAmount"], 0.0)
            self.assertEqual(p_a2["status"], "below_threshold_carried")
            
            # 4. Test above-threshold logic. If min payout is 50.0 instead, walletA (84.75) should be pending_manual_payment
            os.environ["PEPEPOW_MIN_PAYOUT"] = "50.0"
            rc_thresh = payout_helper.generate_payout_candidates(
                self.accepted_path, self.rounds_path, self.output_path, carry_path
            )
            self.assertEqual(rc_thresh, 0)
            with self.output_path.open("r", encoding="utf-8") as f:
                output_thresh = json.load(f)
            items_thresh = {item["candidate_hash"]: item for item in output_thresh.get("items", [])}
            payouts_thresh_el1 = {p["wallet"]: p for p in items_thresh["hash_eligible_1"]["payouts"]}
            self.assertEqual(payouts_thresh_el1["walletA"]["status"], "pending_manual_payment")
            self.assertEqual(payouts_thresh_el1["walletB"]["status"], "below_threshold_carried")
            
            # 5. Test malformed carry snapshot does not crash and applies zero carry
            with carry_path.open("w", encoding="utf-8") as f:
                f.write("{invalid_json}")
            rc_mal = payout_helper.generate_payout_candidates(
                self.accepted_path, self.rounds_path, self.output_path, carry_path
            )
            self.assertEqual(rc_mal, 0)
            with self.output_path.open("r", encoding="utf-8") as f:
                output_mal = json.load(f)
            items_mal = {item["candidate_hash"]: item for item in output_mal.get("items", [])}
            p_a_mal = {p["wallet"]: p for p in items_mal["hash_eligible_1"]["payouts"]}["walletA"]
            self.assertEqual(p_a_mal["carryInAmount"], 0.0)
            self.assertEqual(p_a_mal["amount"], p_a_mal["baseAmount"])
            
        finally:
            os.environ.pop("PEPEPOW_MIN_PAYOUT", None)

    def test_record_payment_clears_carry(self):
        # 1. Setup mock files
        candidates_file = self.tmp_path / "payout-candidates.json"
        carry_file = self.tmp_path / "payout-carry-snapshot.json"
        
        candidates_data = {
            "items": [
                {
                    "candidateId": "candpaid1000000000000000000000001",
                    "height": 100,
                    "blockHash": "hash1000000000000000000000000001",
                    "payouts": [
                        {
                            "wallet": "walletA00000000000000000000000001",
                            "amount": 100.0,
                            "baseAmount": 40.0,
                            "carryInAmount": 60.0,
                            "status": "pending_manual_payment",
                            "carrySourceCandidateIds": ["candsource1000000000000000000001", "candsource2000000000000000000001"]
                        },
                        {
                            "wallet": "walletB00000000000000000000000001",
                            "amount": 50.0,
                            "baseAmount": 50.0,
                            "carryInAmount": 0.0,
                            "status": "below_threshold_carried",
                            "carrySourceCandidateIds": []
                        }
                    ]
                }
            ]
        }
        with candidates_file.open("w", encoding="utf-8") as f:
            json.dump(candidates_data, f)
            
        carry_data = {
            "generatedAt": "2026-06-06T12:00:00Z",
            "items": [
                {
                    "wallet": "walletA00000000000000000000000001",
                    "amount": 40.0,
                    "sourceCandidateId": "candsource1000000000000000000001",
                    "status": "below_threshold_carried"
                },
                {
                    "wallet": "walletA00000000000000000000000001",
                    "amount": 20.0,
                    "sourceCandidateId": "candsource2000000000000000000001",
                    "status": "below_threshold_carried"
                },
                {
                    "wallet": "walletA00000000000000000000000001",
                    "amount": 5.0,
                    "sourceCandidateId": "candunrelatedsource1000000000001", # Unrelated source id for same wallet
                    "status": "below_threshold_carried"
                },
                {
                    "wallet": "walletB00000000000000000000000001", # Unrelated wallet
                    "amount": 15.0,
                    "sourceCandidateId": "candsource1000000000000000000001",
                    "status": "below_threshold_carried"
                }
            ]
        }
        with carry_file.open("w", encoding="utf-8") as f:
            json.dump(carry_data, f)

        # 2. Test recording a payment for walletA on candpaid1000000000000000000000001 clears consumed carry
        rc = payout_helper.record_payment(
            self.actions_log,
            self.snapshot_path,
            candidate_id="candpaid1000000000000000000000001",
            wallet="walletA00000000000000000000000001",
            amount=100.0,
            txid="txid1234567890abcdef1234567890ab"
        )
        self.assertEqual(rc, 0)
        
        # Verify carry_file items: only candunrelatedsource1000000000001 and walletB should remain
        with carry_file.open("r", encoding="utf-8") as f:
            updated_carry = json.load(f)
            
        items = updated_carry.get("items", [])
        self.assertEqual(len(items), 2)
        
        item_map = {(item["wallet"], item["sourceCandidateId"]): item for item in items}
        self.assertIn(("walletA00000000000000000000000001", "candunrelatedsource1000000000001"), item_map)
        self.assertIn(("walletB00000000000000000000000001", "candsource1000000000000000000001"), item_map)
        self.assertNotIn(("walletA00000000000000000000000001", "candsource1000000000000000000001"), item_map)
        self.assertNotIn(("walletA00000000000000000000000001", "candsource2000000000000000000001"), item_map)
        
        # 3. Test failed duplicate payment does not clear carry
        # Record duplicate payment (same candidate + wallet) -> should fail
        rc_dup = payout_helper.record_payment(
            self.actions_log,
            self.snapshot_path,
            candidate_id="candpaid1000000000000000000000001",
            wallet="walletA00000000000000000000000001",
            amount=100.0,
            txid="txiddifferent12345600000000000ab"
        )
        self.assertEqual(rc_dup, 1)
        
        # Verify carry remains unchanged
        with carry_file.open("r", encoding="utf-8") as f:
            carry_after_dup = json.load(f)
        self.assertEqual(len(carry_after_dup.get("items", [])), 2)

        # 4. Test failed duplicate/invalid format check does not clear carry
        rc_invalid = payout_helper.record_payment(
            self.actions_log,
            self.snapshot_path,
            candidate_id="invalid!!!!!!!!!!", # too short or invalid chars
            wallet="walletA00000000000000000000000001",
            amount=100.0,
            txid="txid12300000000000000000000000ab"
        )
        self.assertEqual(rc_invalid, 1)
        
        # Verify carry remains unchanged
        with carry_file.open("r", encoding="utf-8") as f:
            carry_after_invalid = json.load(f)
        self.assertEqual(len(carry_after_invalid.get("items", [])), 2)

        # 5. Test no carry metadata does not touch carry snapshot
        # Recording payment for walletB (which has carryInAmount = 0.0)
        rc_b = payout_helper.record_payment(
            self.actions_log,
            self.snapshot_path,
            candidate_id="candpaid1000000000000000000000001",
            wallet="walletB00000000000000000000000001",
            amount=50.0,
            txid="txidb1234567890abcdef123456789ab"
        )
        self.assertEqual(rc_b, 0)
        
        # Verify walletB's carry of candsource1000000000000000000001 is still present since it wasn't consumed
        with carry_file.open("r", encoding="utf-8") as f:
            carry_after_b = json.load(f)
        items_b = carry_after_b.get("items", [])
        self.assertEqual(len(items_b), 2)
        
        # 6. Test missing carry snapshot does not crash
        carry_file.unlink()
        rc_missing = payout_helper.record_payment(
            self.actions_log,
            self.snapshot_path,
            candidate_id="candpaid1000000000000000000000002",
            wallet="walletA00000000000000000000000001",
            amount=200.0,
            txid="txidnew1234567890abcdef1234567ab"
        )
        self.assertEqual(rc_missing, 0)
        
        # 7. Test malformed carry snapshot does not crash and does not invent state
        with carry_file.open("w", encoding="utf-8") as f:
            f.write("{invalid_json}")
        rc_malformed = payout_helper.record_payment(
            self.actions_log,
            self.snapshot_path,
            candidate_id="candpaid1000000000000000000000003",
            wallet="walletA00000000000000000000000001",
            amount=300.0,
            txid="txidnew2224567890abcdef1234567ab"
        )
        self.assertEqual(rc_malformed, 0)
        # Verify it remains unchanged as malformed string
        with carry_file.open("r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content, "{invalid_json}")

    def test_audit_carry_consistency(self):
        import io
        import sys

        # Setup mock files
        candidates_file = self.tmp_path / "payout-candidates.json"
        carry_file = self.tmp_path / "payout-carry-snapshot.json"
        payments_file = self.tmp_path / "payments-snapshot.json"

        # A. Perfect/OK state
        candidates_data = {
            "items": [
                {
                    "candidateId": "height-100",
                    "status": "ready_for_manual_review",
                    "lifecycleStatus": "confirmed",
                    "payouts": [
                        {
                            "wallet": "walletA",
                            "amount": 100.0,
                            "baseAmount": 40.0,
                            "carryInAmount": 60.0,
                            "carrySourceCandidateIds": ["height-99"]
                        }
                    ]
                }
            ]
        }
        carry_data = {
            "generatedAt": "2026-06-07T00:00:00Z",
            "items": [
                {
                    "wallet": "walletB",
                    "amount": 5.0,
                    "sourceCandidateId": "height-100", # below threshold, carried
                    "status": "below_threshold_carried"
                }
            ]
        }
        payments_data = {
            "items": [
                {
                    "wallet": "walletA",
                    "amount": 100.0,
                    "candidateId": "height-100",
                    "status": "paid_manual"
                }
            ]
        }

        with candidates_file.open("w", encoding="utf-8") as f:
            json.dump(candidates_data, f)
        with carry_file.open("w", encoding="utf-8") as f:
            json.dump(carry_data, f)
        with payments_file.open("w", encoding="utf-8") as f:
            json.dump(payments_data, f)

        # Capture stdout
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            rc = payout_helper.audit_carry_consistency(candidates_file, carry_file, payments_file)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertEqual(rc, 0)
        res = json.loads(output)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["summary"]["malformedInput"], False)
        self.assertEqual(res["summary"]["carryItems"], 1)
        self.assertEqual(res["summary"]["candidateItems"], 1)
        self.assertEqual(res["summary"]["paymentItems"], 1)

        # B. Duplicate carry
        carry_data["items"].append({
            "wallet": "walletB",
            "amount": 5.0,
            "sourceCandidateId": "height-100",
            "status": "below_threshold_carried"
        })
        with carry_file.open("w", encoding="utf-8") as f:
            json.dump(carry_data, f)

        sys.stdout = io.StringIO()
        try:
            rc = payout_helper.audit_carry_consistency(candidates_file, carry_file, payments_file)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertEqual(rc, 1) # should return 1 because there are issues
        res = json.loads(output)
        self.assertEqual(res["status"], "warning")
        self.assertEqual(res["summary"]["duplicateCarryItems"], 1)
        self.assertTrue(any("Duplicate carry item" in issue for issue in res["issues"]))

        # C. Paid carry still present
        # Clear duplicates, make walletB carried source candidate "height-100" already paid
        carry_data["items"] = [
            {
                "wallet": "walletB",
                "amount": 5.0,
                "sourceCandidateId": "height-100",
                "status": "below_threshold_carried"
            }
        ]
        payments_data["items"].append({
            "wallet": "walletB",
            "amount": 5.0,
            "candidateId": "height-100",
            "status": "paid_manual"
        })
        with carry_file.open("w", encoding="utf-8") as f:
            json.dump(carry_data, f)
        with payments_file.open("w", encoding="utf-8") as f:
            json.dump(payments_data, f)

        sys.stdout = io.StringIO()
        try:
            rc = payout_helper.audit_carry_consistency(candidates_file, carry_file, payments_file)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertEqual(rc, 1)
        res = json.loads(output)
        self.assertEqual(res["status"], "warning")
        self.assertEqual(res["summary"]["paidCarryStillPresent"], 1)
        self.assertTrue(any("already recorded as paid" in issue for issue in res["issues"]))

        # D. Blocked carry
        candidates_data["items"][0]["status"] = "blocked"
        candidates_data["items"][0]["lifecycleStatus"] = "orphan"
        with candidates_file.open("w", encoding="utf-8") as f:
            json.dump(candidates_data, f)
        # remove from payments to isolate blocked carry warning
        payments_data["items"] = []
        with payments_file.open("w", encoding="utf-8") as f:
            json.dump(payments_data, f)

        sys.stdout = io.StringIO()
        try:
            rc = payout_helper.audit_carry_consistency(candidates_file, carry_file, payments_file)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertEqual(rc, 1)
        res = json.loads(output)
        self.assertEqual(res["status"], "warning")
        self.assertEqual(res["summary"]["orphanOrBlockedCarryItems"], 1)
        self.assertTrue(any("blocked/orphan/immature" in issue for issue in res["issues"]))

        # E. Payout with carry but missing carrySourceCandidateIds
        candidates_data["items"][0]["status"] = "ready_for_manual_review"
        candidates_data["items"][0]["lifecycleStatus"] = "confirmed"
        candidates_data["items"][0]["payouts"][0]["carrySourceCandidateIds"] = [] # missing/empty
        with candidates_file.open("w", encoding="utf-8") as f:
            json.dump(candidates_data, f)
        # Clear carry to isolate
        carry_data["items"] = []
        with carry_file.open("w", encoding="utf-8") as f:
            json.dump(carry_data, f)

        sys.stdout = io.StringIO()
        try:
            rc = payout_helper.audit_carry_consistency(candidates_file, carry_file, payments_file)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertEqual(rc, 1)
        res = json.loads(output)
        self.assertEqual(res["status"], "warning")
        self.assertTrue(any("missing or empty carrySourceCandidateIds" in issue for issue in res["issues"]))

        # F. Malformed input
        with carry_file.open("w", encoding="utf-8") as f:
            f.write("invalid json")

        sys.stdout = io.StringIO()
        try:
            rc = payout_helper.audit_carry_consistency(candidates_file, carry_file, payments_file)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertEqual(rc, 1)
        res = json.loads(output)
        self.assertEqual(res["status"], "warning")
        self.assertEqual(res["summary"]["malformedInput"], True)

    def test_payout_review_carry_summary(self):
        import io
        import sys

        # Setup mock files
        candidates_file = self.tmp_path / "payout-candidates.json"
        carry_file = self.tmp_path / "payout-carry-snapshot.json"
        payments_file = self.tmp_path / "payments-snapshot.json"

        # A. Clean state with carry and candidate carry applied
        candidates_data = {
            "items": [
                {
                    "candidate_hash": "hash_cand_1",
                    "status": "ready_for_manual_review",
                    "lifecycle_status": "confirmed",
                    "height": 100,
                    "payouts": [
                        {
                            "wallet": "walletA",
                            "amount": 100.0,
                            "baseAmount": 40.0,
                            "carryInAmount": 60.0,
                            "carrySourceCandidateIds": ["height-99"]
                        }
                    ]
                }
            ]
        }
        carry_data = {
            "generatedAt": "2026-06-07T00:00:00Z",
            "items": [
                {
                    "wallet": "walletB",
                    "amount": 5.0,
                    "sourceCandidateId": "height-99",
                    "status": "below_threshold_carried"
                },
                {
                    "wallet": "walletC",
                    "amount": 10.5,
                    "sourceCandidateId": "height-99",
                    "status": "below_threshold_carried"
                }
            ]
        }
        payments_data = {
            "items": []
        }

        with candidates_file.open("w", encoding="utf-8") as f:
            json.dump(candidates_data, f)
        with carry_file.open("w", encoding="utf-8") as f:
            json.dump(carry_data, f)
        with payments_file.open("w", encoding="utf-8") as f:
            json.dump(payments_data, f)

        # 1. Test full review output
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            rc = payout_helper.payout_review(candidates_file, carry_file, payments_file)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertEqual(rc, 0)
        self.assertIn("Payout Candidates", output)
        self.assertIn("Candidate: hash_cand_1 (Height: 100, Lifecycle: confirmed)", output)
        self.assertIn("Payout Status: READY_FOR_MANUAL_REVIEW", output)
        self.assertIn("Carry Status Summary", output)
        # New compact format: ready_payment_total, below_threshold_carry_total, wallet_carry_count, blocked_candidates
        self.assertIn("ready_payment_total:", output)
        self.assertIn("below_threshold_carry_total: 15.5", output)
        self.assertIn("wallet_carry_count: 2", output)
        self.assertIn("blocked_candidates: 0", output)
        self.assertIn("carry_audit_status: ok", output)

        # 2. Test missing files (should not crash, return zeros/unknowns)
        missing_carry = self.tmp_path / "nonexistent-carry.json"
        missing_candidates = self.tmp_path / "nonexistent-candidates.json"
        
        sys.stdout = io.StringIO()
        try:
            rc = payout_helper.payout_review(missing_candidates, missing_carry, payments_file)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertEqual(rc, 0)
        self.assertIn("No candidates found.", output)
        self.assertIn("below_threshold_carry_total: 0.0", output)
        self.assertIn("wallet_carry_count: 0", output)
        self.assertIn("carry_audit_status: warning", output)

        # 3. Test malformed carry snapshot (should not crash, return zeros/unknowns)
        malformed_carry = self.tmp_path / "malformed-carry.json"
        with malformed_carry.open("w", encoding="utf-8") as f:
            f.write("{invalid_json}")
            
        sys.stdout = io.StringIO()
        try:
            rc = payout_helper.payout_review(candidates_file, malformed_carry, payments_file)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertEqual(rc, 0)
        self.assertIn("below_threshold_carry_total: 0.0", output)
        self.assertIn("wallet_carry_count: 0", output)
        self.assertIn("carry_audit_status: warning", output)

    def test_payout_review_json(self):
        import io
        import sys

        # Setup mock files
        candidates_file = self.tmp_path / "payout-candidates.json"
        carry_file = self.tmp_path / "payout-carry-snapshot.json"
        payments_file = self.tmp_path / "payments-snapshot.json"

        # A. Clean state with carry and candidate carry applied
        candidates_data = {
            "items": [
                {
                    "candidateId": "hash_cand_1",
                    "candidate_hash": "hash_cand_1",
                    "status": "ready_for_manual_review",
                    "lifecycleStatus": "confirmed",
                    "lifecycle_status": "confirmed",
                    "height": 100,
                    "netReward": 500.0,
                    "net_reward": 500.0,
                    "payouts": [
                        {
                            "wallet": "walletA",
                            "amount": 100.0,
                            "baseAmount": 40.0,
                            "carryInAmount": 60.0,
                            "carrySourceCandidateIds": ["height-99"]
                        }
                    ]
                }
            ]
        }
        carry_data = {
            "generatedAt": "2026-06-07T00:00:00Z",
            "items": [
                {
                    "wallet": "walletB",
                    "amount": 5.0,
                    "sourceCandidateId": "height-99",
                    "status": "below_threshold_carried"
                }
            ]
        }
        payments_data = {
            "items": [
                {
                    "wallet": "walletA",
                    "amount": 100.0,
                    "candidateId": "height-100",
                    "status": "paid_manual"
                }
            ]
        }

        with candidates_file.open("w", encoding="utf-8") as f:
            json.dump(candidates_data, f)
        with carry_file.open("w", encoding="utf-8") as f:
            json.dump(carry_data, f)
        with payments_file.open("w", encoding="utf-8") as f:
            json.dump(payments_data, f)

        # 1. Test json review output format and content
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            rc = payout_helper.payout_review(candidates_file, carry_file, payments_file, as_json=True)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertEqual(rc, 0)
        res = json.loads(output)
        
        self.assertEqual(res["status"], "ok")
        self.assertIn("generatedAt", res)
        summary = res["summary"]
        self.assertEqual(summary["candidateItems"], 1)
        self.assertEqual(summary["readyCandidates"], 1)
        self.assertEqual(summary["blockedCandidates"], 0)
        self.assertEqual(summary["paymentRows"], 1)
        self.assertEqual(summary["carryItems"], 1)
        self.assertEqual(summary["carryTotalAmount"], 5.0)
        self.assertEqual(summary["walletsWithCarry"], ["walletB"])
        self.assertEqual(summary["candidatePayoutsWithCarry"], 1)
        self.assertEqual(summary["candidateCarryAppliedAmount"], 60.0)
        self.assertEqual(summary["carryAuditStatus"], "ok")

        self.assertEqual(len(res["items"]), 1)
        item = res["items"][0]
        self.assertEqual(item["candidateId"], "hash_cand_1")
        self.assertEqual(item["blockHeight"], 100)
        self.assertEqual(item["status"], "ready_for_manual_review")
        self.assertEqual(item["lifecycleStatus"], "confirmed")
        self.assertEqual(item["netReward"], 500.0)
        self.assertEqual(item["payoutCount"], 1)
        self.assertEqual(item["carryAppliedAmount"], 60.0)

        # 2. Test text output still works when as_json is False
        sys.stdout = io.StringIO()
        try:
            rc = payout_helper.payout_review(candidates_file, carry_file, payments_file, as_json=False)
            output_text = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
            
        self.assertEqual(rc, 0)
        self.assertIn("Payout Candidates (Last updated:", output_text)
        self.assertIn("Carry Status Summary", output_text)

        # 3. Test malformed inputs return warning JSON and do not crash
        with carry_file.open("w", encoding="utf-8") as f:
            f.write("malformed json content")
            
        sys.stdout = io.StringIO()
        try:
            rc = payout_helper.payout_review(candidates_file, carry_file, payments_file, as_json=True)
            output_warn = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertEqual(rc, 0)
        res_warn = json.loads(output_warn)
        self.assertEqual(res_warn["status"], "warning")
        self.assertEqual(res_warn["summary"]["carryItems"], 0)
        self.assertEqual(res_warn["summary"]["carryTotalAmount"], 0.0)

    def test_payout_review_check_ready(self):
        """ready label emitted when there is at least one ready candidate."""
        import io as _io

        candidates_file = self.tmp_path / "payout-candidates.json"
        carry_file = self.tmp_path / "payout-carry-snapshot.json"
        payments_file = self.tmp_path / "payments-snapshot.json"

        # Carry items must reference a candidate that exists and is NOT blocked in order for
        # carry_audit_status to stay "ok" (otherwise payout_review returns status: warning).
        # Use a ready_for_manual_review candidate as the carry source.
        candidates_data = {
            "items": [
                {
                    "candidate_hash": "hash_ready_1",
                    "candidateId": "hash_ready_1",
                    "status": "ready_for_manual_review",
                    "lifecycle_status": "confirmed",
                    "lifecycleStatus": "confirmed",
                    "height": 100,
                    "payouts": []
                },
                {
                    "candidate_hash": "hash_blocked_1",
                    "candidateId": "hash_blocked_1",
                    "status": "blocked",
                    "lifecycle_status": "immature",
                    "lifecycleStatus": "immature",
                    "height": 101,
                    "payouts": []
                }
            ]
        }
        # Carry items sourced from the ready candidate (confirmed, not blocked) → audit passes
        carry_data = {"generatedAt": "2026-06-07T00:00:00Z", "items": [
            {"wallet": "walletA", "amount": 1234.5, "sourceCandidateId": "hash_ready_1",
             "status": "below_threshold_carried"},
            {"wallet": "walletB", "amount": 0.0, "sourceCandidateId": "hash_ready_1",
             "status": "below_threshold_carried"},
        ]}
        payments_data = {"items": []}

        with candidates_file.open("w", encoding="utf-8") as f:
            json.dump(candidates_data, f)
        with carry_file.open("w", encoding="utf-8") as f:
            json.dump(carry_data, f)
        with payments_file.open("w", encoding="utf-8") as f:
            json.dump(payments_data, f)

        before_files = set(self.tmp_path.iterdir())

        buf = _io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            rc = payout_helper.payout_review_check(candidates_file, carry_file, payments_file)
        finally:
            sys.stdout = old_stdout
        output = buf.getvalue()

        self.assertEqual(rc, 0)
        self.assertIn("payout_review_check: ready", output)
        self.assertIn("status: ok", output)
        self.assertIn("ready_candidates: 1", output)
        self.assertIn("blocked_candidates: 1", output)
        self.assertIn("carry_items: 2", output)
        self.assertIn("carry_audit_status: ok", output)

        # No new files written
        after_files = set(self.tmp_path.iterdir())
        self.assertEqual(before_files, after_files, "payout_review_check must not write runtime files")

    def test_payout_review_check_no_ready_candidates(self):
        """no-ready-candidates label when all candidates are blocked."""
        import io as _io

        candidates_file = self.tmp_path / "payout-candidates.json"
        carry_file = self.tmp_path / "payout-carry-snapshot.json"
        payments_file = self.tmp_path / "payments-snapshot.json"

        candidates_data = {
            "items": [
                {
                    "candidate_hash": "hash_blocked_2",
                    "candidateId": "hash_blocked_2",
                    "status": "blocked",
                    "lifecycle_status": "immature",
                    "lifecycleStatus": "immature",
                    "height": 200,
                    "payouts": []
                }
            ]
        }
        carry_data = {"generatedAt": "2026-06-07T00:00:00Z", "items": []}
        payments_data = {"items": []}

        with candidates_file.open("w", encoding="utf-8") as f:
            json.dump(candidates_data, f)
        with carry_file.open("w", encoding="utf-8") as f:
            json.dump(carry_data, f)
        with payments_file.open("w", encoding="utf-8") as f:
            json.dump(payments_data, f)

        buf = _io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            rc = payout_helper.payout_review_check(candidates_file, carry_file, payments_file)
        finally:
            sys.stdout = old_stdout
        output = buf.getvalue()

        self.assertEqual(rc, 0)
        self.assertIn("payout_review_check: no-ready-candidates", output)
        self.assertIn("status: ok", output)
        self.assertIn("ready_candidates: 0", output)
        self.assertIn("blocked_candidates: 1", output)

    def test_payout_review_check_warning_on_missing_files(self):
        """warning status and exit code 1 when input files are missing."""
        import io as _io

        missing_candidates = self.tmp_path / "nonexistent-candidates.json"
        missing_carry = self.tmp_path / "nonexistent-carry.json"
        missing_payments = self.tmp_path / "nonexistent-payments.json"

        buf = _io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            rc = payout_helper.payout_review_check(missing_candidates, missing_carry, missing_payments)
        finally:
            sys.stdout = old_stdout
        output = buf.getvalue()

        self.assertEqual(rc, 1)
        self.assertIn("payout_review_check: warning", output)
        self.assertIn("status: warning", output)
        self.assertIn("carry_audit_status: warning", output)

    def test_payout_review_check_warning_on_malformed_candidates(self):
        """warning status and exit code 1 when candidates JSON is malformed."""
        import io as _io

        candidates_file = self.tmp_path / "payout-candidates.json"
        carry_file = self.tmp_path / "payout-carry-snapshot.json"
        payments_file = self.tmp_path / "payments-snapshot.json"

        with candidates_file.open("w", encoding="utf-8") as f:
            f.write("{invalid json}")
        with carry_file.open("w", encoding="utf-8") as f:
            json.dump({"generatedAt": "2026-06-07T00:00:00Z", "items": []}, f)
        with payments_file.open("w", encoding="utf-8") as f:
            json.dump({"items": []}, f)

        buf = _io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            rc = payout_helper.payout_review_check(candidates_file, carry_file, payments_file)
        finally:
            sys.stdout = old_stdout
        output = buf.getvalue()

        self.assertEqual(rc, 1)
        self.assertIn("payout_review_check: warning", output)
        self.assertIn("status: warning", output)

    def test_payout_review_check_via_sh(self):
        """payout-review-check command works end-to-end via live-stratum.sh."""
        import subprocess
        import os

        candidates_file = self.tmp_path / "payout-candidates.json"
        carry_file = self.tmp_path / "payout-carry-snapshot.json"
        payments_file = self.tmp_path / "payments-snapshot.json"

        candidates_data = {
            "items": [
                {
                    "candidate_hash": "hashcheckcandidatesh0000000001",
                    "candidateId": "hashcheckcandidatesh0000000001",
                    "status": "ready_for_manual_review",
                    "lifecycle_status": "confirmed",
                    "lifecycleStatus": "confirmed",
                    "height": 300,
                    "payouts": []
                }
            ]
        }
        carry_data = {"generatedAt": "2026-06-07T00:00:00Z", "items": []}
        payments_data = {"items": []}

        with candidates_file.open("w", encoding="utf-8") as f:
            json.dump(candidates_data, f)
        with carry_file.open("w", encoding="utf-8") as f:
            json.dump(carry_data, f)
        with payments_file.open("w", encoding="utf-8") as f:
            json.dump(payments_data, f)

        sh_path = Path(__file__).resolve().parents[1] / "ops" / "scripts" / "live-stratum.sh"
        env = dict(os.environ)
        env["PEPEPOW_LIVE_STRATUM_RUNTIME_DIR"] = str(self.tmp_path)

        before_files = set(self.tmp_path.iterdir())

        res = subprocess.run(
            [str(sh_path), "payout-review-check"],
            env=env,
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0, msg=f"stderr: {res.stderr}")
        self.assertIn("payout_review_check: ready", res.stdout)
        self.assertIn("status: ok", res.stdout)
        self.assertIn("ready_candidates: 1", res.stdout)

        # No new runtime files created beyond what was there before
        after_files = set(self.tmp_path.iterdir())
        self.assertEqual(before_files, after_files, "payout-review-check must not write runtime files")

    def test_payout_monitor_lite_sh(self):
        """payout-monitor-lite.sh cron wrapper works end-to-end and outputs correct status."""
        import subprocess
        import os

        # Test 1: warning (empty/missing runtime directory files)
        monitor_path = Path(__file__).resolve().parents[1] / "ops" / "scripts" / "payout-monitor-lite.sh"
        env_warn = dict(os.environ)
        # Pointing to a clean subfolder ensures no files are present
        warn_dir = self.tmp_path / "warn_subdir"
        warn_dir.mkdir()
        env_warn["PEPEPOW_LIVE_STRATUM_RUNTIME_DIR"] = str(warn_dir)

        res_warn = subprocess.run(
            [str(monitor_path)],
            env=env_warn,
            capture_output=True,
            text=True
        )
        # It should exit with 0 or 1 depending on implementation, but outputs POOL_PAYOUT_WARNING status=warning
        self.assertIn("POOL_PAYOUT_WARNING status=warning", res_warn.stdout)

        # Test 2: no ready candidates
        candidates_file = self.tmp_path / "payout-candidates.json"
        carry_file = self.tmp_path / "payout-carry-snapshot.json"
        payments_file = self.tmp_path / "payments-snapshot.json"

        # All blocked
        candidates_data = {
            "items": [
                {
                    "candidate_hash": "hash_blocked_1",
                    "candidateId": "hash_blocked_1",
                    "status": "blocked",
                    "lifecycle_status": "immature",
                    "lifecycleStatus": "immature",
                    "height": 100,
                    "payouts": []
                }
            ]
        }
        carry_data = {"generatedAt": "2026-06-07T00:00:00Z", "items": []}
        payments_data = {"items": []}

        with candidates_file.open("w", encoding="utf-8") as f:
            json.dump(candidates_data, f)
        with carry_file.open("w", encoding="utf-8") as f:
            json.dump(carry_data, f)
        with payments_file.open("w", encoding="utf-8") as f:
            json.dump(payments_data, f)

        env_ok = dict(os.environ)
        env_ok["PEPEPOW_LIVE_STRATUM_RUNTIME_DIR"] = str(self.tmp_path)

        before_files = set(self.tmp_path.iterdir())

        # Piped/Captured stdout (non-TTY) -> should be silent
        res_ok = subprocess.run(
            [str(monitor_path)],
            env=env_ok,
            capture_output=True,
            text=True
        )
        self.assertEqual(res_ok.returncode, 0)
        self.assertEqual(res_ok.stdout, "")

        # Test 3: ready candidate
        candidates_data_ready = {
            "items": [
                {
                    "candidate_hash": "hash_ready_1",
                    "candidateId": "hash_ready_1",
                    "status": "ready_for_manual_review",
                    "lifecycle_status": "confirmed",
                    "lifecycleStatus": "confirmed",
                    "height": 200,
                    "payouts": []
                }
            ]
        }
        with candidates_file.open("w", encoding="utf-8") as f:
            json.dump(candidates_data_ready, f)

        res_ready = subprocess.run(
            [str(monitor_path)],
            env=env_ok,
            capture_output=True,
            text=True
        )
        self.assertEqual(res_ready.returncode, 0)
        self.assertIn("POOL_PAYOUT_READY ready_candidates=1", res_ready.stdout)

        # No new runtime files created beyond what was there before (excluding the warn_subdir and created test files)
        after_files = set(self.tmp_path.iterdir())
        new_files = after_files - before_files
        self.assertEqual(new_files, set(), f"Should not write runtime files during execution. New files: {new_files}")


class CarryFocusedTests(unittest.TestCase):
    """Focused tests for balance carry support (spec §Tests)."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.accepted_path = self.tmp_path / "accepted-candidates.json"
        self.rounds_path = self.tmp_path / "rounds-snapshot.json"
        self.output_path = self.tmp_path / "payout-candidates.json"
        self.carry_path = self.tmp_path / "payout-carry-snapshot.json"
        self.actions_log = self.tmp_path / "payment-actions.jsonl"
        self.snapshot_path = self.tmp_path / "payments-snapshot.json"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _write_accepted(self, cands):
        with self.accepted_path.open("w", encoding="utf-8") as f:
            json.dump({"accepted_candidates": cands}, f)

    def _write_rounds(self, rounds):
        with self.rounds_path.open("w", encoding="utf-8") as f:
            json.dump({"rounds": rounds}, f)

    def _write_carry(self, items):
        with self.carry_path.open("w", encoding="utf-8") as f:
            json.dump({"generatedAt": "2026-06-07T00:00:00Z", "items": items}, f)

    def _run_candidates(self, carry=None):
        return payout_helper.generate_payout_candidates(
            self.accepted_path, self.rounds_path, self.output_path,
            carry or self.carry_path if self.carry_path.exists() else None
        )

    def _load_output(self):
        with self.output_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def test_below_threshold_amount_becomes_carried(self):
        """A payout amount below PEPEPOW_MIN_PAYOUT is marked below_threshold_carried (not pending)."""
        import os
        os.environ["PEPEPOW_MIN_PAYOUT"] = "1000.0"
        try:
            self._write_accepted([{
                "candidate_hash": "candabcdefghijklmnopqrstuvwx001",
                "lifecycle_status": "confirmed",
                "matched_height": 100,
                "submit_timestamp": "2026-06-07T00:00:00Z",
                "reward": 10.0  # small reward -> net ~9.9, well below 1000
            }])
            self._write_rounds([{
                "candidate_hash": "candabcdefghijklmnopqrstuvwx001",
                "total_share_score": 10.0,
                "total_share_count": 10,
                "shares": {
                    "walletXYZ0000000000000000000001": {
                        "share_count": 10,
                        "share_score": 10.0,
                        "share_percent": 100.0
                    }
                }
            }])
            rc = payout_helper.generate_payout_candidates(
                self.accepted_path, self.rounds_path, self.output_path
            )
            self.assertEqual(rc, 0)
            data = self._load_output()
            items = data["items"]
            self.assertEqual(len(items), 1)
            cand = items[0]
            self.assertEqual(cand["status"], "ready_for_manual_review")
            self.assertEqual(len(cand["payouts"]), 1)
            p = cand["payouts"][0]
            self.assertEqual(p["wallet"], "walletXYZ0000000000000000000001")
            self.assertEqual(p["status"], "below_threshold_carried",
                             "Amount below min_payout must be marked below_threshold_carried")
            self.assertAlmostEqual(p["carryInAmount"], 0.0)
            self.assertLess(p["amount"], 1000.0)
        finally:
            os.environ.pop("PEPEPOW_MIN_PAYOUT", None)

    def test_carried_amount_combines_with_later_candidate(self):
        """A carried amount from a prior block is included in a later eligible candidate's payout,
        and if combined total reaches threshold the status becomes pending_manual_payment."""
        import os
        os.environ["PEPEPOW_MIN_PAYOUT"] = "100.0"
        try:
            # Prior carry: walletABC previously earned 80.0 but was below threshold
            self._write_carry([{
                "wallet": "walletABC000000000000000000001",
                "amount": 80.0,
                "sourceCandidateId": "candprev000000000000000000000001",
                "sourceBlockHeight": 99,
                "sourceBlockHash": "hashprev000000000000000000000001",
                "status": "below_threshold_carried"
            }])

            # New block: walletABC earns 30.0 net (base). 80 + 30 = 110 >= 100 threshold
            self._write_accepted([{
                "candidate_hash": "candnew0000000000000000000000001",
                "lifecycle_status": "confirmed",
                "matched_height": 101,
                "submit_timestamp": "2026-06-07T00:01:00Z",
                "reward": 30.3030  # ~30.0 net after 1% fee
            }])
            self._write_rounds([{
                "candidate_hash": "candnew0000000000000000000000001",
                "total_share_score": 10.0,
                "total_share_count": 10,
                "shares": {
                    "walletABC000000000000000000001": {
                        "share_count": 10,
                        "share_score": 10.0,
                        "share_percent": 100.0
                    }
                }
            }])
            rc = self._run_candidates()
            self.assertEqual(rc, 0)
            data = self._load_output()
            items = data["items"]
            self.assertEqual(len(items), 1)
            payouts = items[0]["payouts"]
            self.assertEqual(len(payouts), 1)
            p = payouts[0]
            self.assertEqual(p["wallet"], "walletABC000000000000000000001")
            self.assertAlmostEqual(p["carryInAmount"], 80.0,
                                   msg="Carry-in amount must be included from prior below-threshold")
            self.assertGreater(p["amount"], 100.0,
                               msg="Combined amount must exceed threshold")
            self.assertEqual(p["status"], "pending_manual_payment",
                             "Combined carry+base >= threshold must be pending_manual_payment")
            self.assertIn("candprev000000000000000000000001", p["carrySourceCandidateIds"])
        finally:
            os.environ.pop("PEPEPOW_MIN_PAYOUT", None)

    def test_carry_clears_after_record_payment(self):
        """When a manual payment is recorded for a wallet, its consumed carry entries are removed
        from the carry snapshot atomically."""
        # Build candidates snapshot with carry metadata
        candidates_data = {
            "items": [{
                "candidateId": "candpaidXXXXXXXXXXXXXXXXXXXXXX01",
                "candidate_hash": "candpaidXXXXXXXXXXXXXXXXXXXXXX01",
                "height": 200,
                "blockHash": "candpaidXXXXXXXXXXXXXXXXXXXXXX01",
                "payouts": [{
                    "wallet": "walletPAID000000000000000000001",
                    "amount": 150.0,
                    "baseAmount": 50.0,
                    "carryInAmount": 100.0,
                    "status": "pending_manual_payment",
                    "carrySourceCandidateIds": ["candsrcAAAAAAAAAAAAAAAAAAAAAAA01"]
                }]
            }]
        }
        with self.output_path.open("w", encoding="utf-8") as f:
            json.dump(candidates_data, f)

        # Carry snapshot has 2 entries for this wallet + 1 for another wallet
        self._write_carry([
            {
                "wallet": "walletPAID000000000000000000001",
                "amount": 100.0,
                "sourceCandidateId": "candsrcAAAAAAAAAAAAAAAAAAAAAAA01",
                "status": "below_threshold_carried"
            },
            {
                "wallet": "walletPAID000000000000000000001",
                "amount": 5.0,
                "sourceCandidateId": "candsrcBBBBBBBBBBBBBBBBBBBBBBB01",  # unrelated source
                "status": "below_threshold_carried"
            },
            {
                "wallet": "walletOTHER00000000000000000001",  # different wallet, untouched
                "amount": 20.0,
                "sourceCandidateId": "candsrcAAAAAAAAAAAAAAAAAAAAAAA01",
                "status": "below_threshold_carried"
            }
        ])

        rc = payout_helper.record_payment(
            self.actions_log,
            self.snapshot_path,
            candidate_id="candpaidXXXXXXXXXXXXXXXXXXXXXX01",
            wallet="walletPAID000000000000000000001",
            amount=150.0,
            txid="txidCARRYCLEARTEST0000000000001"
        )
        self.assertEqual(rc, 0)

        with self.carry_path.open("r", encoding="utf-8") as f:
            updated_carry = json.load(f)

        remaining = updated_carry["items"]
        # Only candsrcBBB (unrelated source for paid wallet) and walletOTHER should remain
        self.assertEqual(len(remaining), 2,
                         "Consumed carry entries must be cleared; unrelated ones must remain")
        remaining_keys = {(i["wallet"], i["sourceCandidateId"]) for i in remaining}
        self.assertIn(("walletPAID000000000000000000001", "candsrcBBBBBBBBBBBBBBBBBBBBBBB01"), remaining_keys,
                      "Unrelated source for paid wallet must remain in carry")
        self.assertIn(("walletOTHER00000000000000000001", "candsrcAAAAAAAAAAAAAAAAAAAAAAA01"), remaining_keys,
                      "Other wallet's carry entry must remain untouched")
        self.assertNotIn(("walletPAID000000000000000000001", "candsrcAAAAAAAAAAAAAAAAAAAAAAA01"), remaining_keys,
                         "Consumed carry entry must be removed")

    def test_blocked_already_paid_still_blocks_duplicate(self):
        """A candidate where payment was already recorded is blocked with blocked_already_paid
        even if re-generated; and a second record_payment attempt for same candidate+wallet is rejected."""
        # Write an existing payment action for a candidate
        existing_action = {
            "candidate_id": "candduplicatestopperXXXXXXXXX001",
            "wallet": "walletDUP000000000000000000001",
            "amount": 500.0,
            "txid": "txidDUPLICATESTOP00000000000001",
            "timestamp": "2026-06-07T00:00:00Z"
        }
        with (self.output_path.parent / "payment-actions.jsonl").open("w", encoding="utf-8") as f:
            f.write(json.dumps(existing_action) + "\n")

        # Now generate candidates that include this already-paid candidate
        self._write_accepted([{
            "candidate_hash": "candduplicatestopperXXXXXXXXX001",
            "lifecycle_status": "confirmed",
            "matched_height": 300,
            "submit_timestamp": "2026-06-07T00:00:00Z",
            "reward": 50000.0
        }])
        self._write_rounds([{
            "candidate_hash": "candduplicatestopperXXXXXXXXX001",
            "total_share_score": 10.0,
            "total_share_count": 10,
            "shares": {
                "walletDUP000000000000000000001": {
                    "share_count": 10,
                    "share_score": 10.0,
                    "share_percent": 100.0
                }
            }
        }])
        rc = payout_helper.generate_payout_candidates(
            self.accepted_path, self.rounds_path, self.output_path
        )
        self.assertEqual(rc, 0)
        data = self._load_output()
        cand = data["items"][0]
        self.assertEqual(cand["status"], "blocked",
                         "Already-paid candidate must be blocked")
        self.assertEqual(cand["reason"], "blocked_already_paid",
                         "Block reason must be blocked_already_paid")

        # Also verify that record_payment rejects a duplicate for the same candidate+wallet
        rc_dup = payout_helper.record_payment(
            self.actions_log,
            self.snapshot_path,
            candidate_id="candduplicatestopperXXXXXXXXX001",
            wallet="walletDUP000000000000000000001",
            amount=500.0,
            txid="txidDUPLICATE2222200000000000001"
        )
        self.assertEqual(rc_dup, 1,
                         "record_payment must reject duplicate candidate_id+wallet pair")


import unittest.mock

class WalletRpcDryRunTests(unittest.TestCase):
    """Focused tests for the Wallet RPC dry-run payout intent layer."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.candidates_path = self.tmp_path / "payout-candidates.json"
        self.output_path = self.tmp_path / "payout-wallet-dry-run.json"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _write_candidates(self, items):
        with self.candidates_path.open("w", encoding="utf-8") as f:
            json.dump({"items": items, "updated_at": "2026-06-07T00:00:00Z"}, f)

    @unittest.mock.patch('payout_helper.wallet_readonly_call')
    def test_dry_run_creates_artifact(self, mock_wallet):
        """Dry-run validates candidates and writes output snapshot atomically with correct fields."""
        def side_effect(method, params):
            if method == "getbalance":
                return 50000.0
            if method == "validateaddress":
                return {"isvalid": True}
            return None
        mock_wallet.side_effect = side_effect

        self._write_candidates([
            {
                "candidateId": "candeligible000000000000000001",
                "blockHash": "candeligible000000000000000001",
                "height": 500,
                "status": "ready_for_manual_review",
                "payouts": [
                    {
                        "wallet": "PEPEPOW1WalletAddressTarget001",
                        "amount": 120.5,
                        "status": "pending_manual_payment"
                    },
                    {
                        "wallet": "PEPEPOW1WalletAddressTarget002",
                        "amount": 50.0,
                        "status": "below_threshold_carried"
                    }
                ]
            }
        ])

        rc = payout_helper.payout_wallet_dry_run(self.candidates_path, self.output_path)
        self.assertEqual(rc, 0)
        self.assertTrue(self.output_path.exists())

        with self.output_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["mode"], "dry_run")
        self.assertEqual(data["realSendEnabled"], False)
        self.assertAlmostEqual(data["totalReadyAmount"], 120.5)
        self.assertAlmostEqual(data["walletAvailableBalance"], 50000.0)
        self.assertEqual(data["readyCount"], 1)
        self.assertEqual(data["blockedCount"], 0)
        self.assertTrue(data["walletBalanceReadOk"])
        self.assertFalse(data["insufficientBalance"])
        self.assertEqual(data["item count"], 1)
        self.assertEqual(data["blocked items"], 0)
        self.assertEqual(len(data["warnings"]), 0)

        items = data["items"]
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["candidateId"], "candeligible000000000000000001")
        self.assertEqual(item["wallet"], "PEPEPOW1WalletAddressTarget001")
        self.assertAlmostEqual(item["amount"], 120.5)
        self.assertEqual(item["status"], "ready_for_wallet_send_preview")
        self.assertEqual(item["validationMode"], "rpc")
        self.assertEqual(item["rpcWouldSend"], False)

    @unittest.mock.patch('payout_helper.wallet_readonly_call')
    def test_dry_run_does_not_call_send_rpc(self, mock_wallet):
        """Dry-run verifies balance and address but never calls any transaction-sending RPC methods."""
        mock_wallet.return_value = None

        self._write_candidates([
            {
                "candidateId": "candeligible000000000000000001",
                "blockHash": "candeligible000000000000000001",
                "height": 500,
                "status": "ready_for_manual_review",
                "payouts": [
                    {
                        "wallet": "PEPEPOW1WalletAddressTarget001",
                        "amount": 100.0,
                        "status": "pending_manual_payment"
                    }
                ]
            }
        ])

        rc = payout_helper.payout_wallet_dry_run(self.candidates_path, self.output_path)
        self.assertEqual(rc, 0)

        called_methods = [call[0][0] for call in mock_wallet.call_args_list]
        for method in called_methods:
            self.assertNotIn(method, ["sendtoaddress", "sendmany", "walletpassphrase", "walletunlock"])

        with self.output_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertFalse(data["walletBalanceReadOk"])
        self.assertTrue(data["insufficientBalance"])
        self.assertIn("Wallet RPC unreachable or balance unreadable", data["warnings"])

    @unittest.mock.patch('payout_helper.wallet_readonly_call')
    def test_insufficient_balance_blocks_output(self, mock_wallet):
        """When total payouts exceed available wallet balance, items are marked blocked_insufficient_balance."""
        def side_effect(method, params):
            if method == "getbalance":
                return 50.0
            if method == "validateaddress":
                return {"isvalid": True}
            return None
        mock_wallet.side_effect = side_effect

        self._write_candidates([
            {
                "candidateId": "candeligible000000000000000001",
                "blockHash": "candeligible000000000000000001",
                "height": 500,
                "status": "ready_for_manual_review",
                "payouts": [
                    {
                        "wallet": "PEPEPOW1WalletAddressTarget001",
                        "amount": 100.0,
                        "status": "pending_manual_payment"
                    }
                ]
            }
        ])

        rc = payout_helper.payout_wallet_dry_run(self.candidates_path, self.output_path)
        self.assertEqual(rc, 0)

        with self.output_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["blocked items"], 1)
        self.assertEqual(data["blockedCount"], 1)
        self.assertEqual(data["readyCount"], 0)
        self.assertTrue(data["insufficientBalance"])
        self.assertEqual(data["items"][0]["status"], "blocked_insufficient_balance")
        self.assertIn("Insufficient wallet balance for ready payouts", data["warnings"])

    @unittest.mock.patch('payout_helper.wallet_readonly_call')
    def test_missing_payout_candidates_returns_empty_dry_run_safely(self, mock_wallet):
        """Missing candidate file is handled gracefully and returns empty dry-run structure."""
        mock_wallet.return_value = 1000.0

        if self.candidates_path.exists():
            self.candidates_path.unlink()

        rc = payout_helper.payout_wallet_dry_run(self.candidates_path, self.output_path)
        self.assertEqual(rc, 0)

        with self.output_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["item count"], 0)
        self.assertEqual(data["blocked items"], 0)
        self.assertEqual(data["readyCount"], 0)
        self.assertEqual(data["blockedCount"], 0)
        self.assertEqual(data["items"], [])


    @unittest.mock.patch.dict(os.environ, {}, clear=False)
    @unittest.mock.patch('payout_helper.query_rpc')
    def test_cli_fallback_can_read_mocked_balance(self, mock_rpc):
        """When RPC config is absent, dry-run can read balance through a configured wallet CLI."""
        mock_rpc.return_value = None
        cli_path = self.tmp_path / "PEPEPOW-cli"
        cli_path.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "if sys.argv[1] == 'getbalance': print('1234.5')\n"
            "elif sys.argv[1] == 'validateaddress': print(json.dumps({'isvalid': True}))\n"
            "else: print(json.dumps({'balance': 1234.5}))\n",
            encoding="utf-8",
        )
        cli_path.chmod(0o755)
        old_cli = os.environ.get("PEPEPOW_WALLET_CLI")
        old_rpc_keys = {k: os.environ.get(k) for k in ["PEPEPOWD_RPC_URL", "PEPEPOWD_RPC_USER", "PEPEPOWD_RPC_PASSWORD"]}
        os.environ["PEPEPOW_WALLET_CLI"] = str(cli_path)
        for key in old_rpc_keys:
            os.environ.pop(key, None)

        try:
            self._write_candidates([
                {
                    "candidateId": "candeligible000000000000000001",
                    "blockHash": "candeligible000000000000000001",
                    "height": 500,
                    "status": "ready_for_manual_review",
                    "payouts": [
                        {
                            "wallet": "PEPEPOW1WalletAddressTarget001",
                            "amount": 100.0,
                            "status": "pending_manual_payment"
                        }
                    ]
                }
            ])

            rc = payout_helper.payout_wallet_dry_run(self.candidates_path, self.output_path)
            self.assertEqual(rc, 0)

            with self.output_path.open("r", encoding="utf-8") as f:
                data = json.load(f)

            self.assertAlmostEqual(data["walletAvailableBalance"], 1234.5)
            self.assertTrue(data["walletBalanceReadOk"])
            self.assertEqual(data["readyCount"], 1)
            mock_rpc.assert_not_called()
        finally:
            if old_cli is None:
                os.environ.pop("PEPEPOW_WALLET_CLI", None)
            else:
                os.environ["PEPEPOW_WALLET_CLI"] = old_cli
            for key, value in old_rpc_keys.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    @unittest.mock.patch('payout_helper.wallet_readonly_call')
    def test_malformed_payout_candidate_is_blocked(self, mock_wallet):
        """Malformed payout candidate with missing/invalid fields gets blocked."""
        def side_effect(method, params):
            if method == "getbalance":
                return 1000.0
            if method == "validateaddress":
                return {"isvalid": True}
            return None
        mock_wallet.side_effect = side_effect

        self._write_candidates([
            {
                "height": -10,
                "status": "ready_for_manual_review",
                "payouts": [
                    {
                        "wallet": "PEPEPOW1WalletAddressTarget001",
                        "amount": 10.0,
                        "status": "pending_manual_payment"
                    }
                ]
            }
        ])

        rc = payout_helper.payout_wallet_dry_run(self.candidates_path, self.output_path)
        self.assertEqual(rc, 0)

        with self.output_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["blocked items"], 1)
        self.assertEqual(data["items"][0]["status"], "blocked_malformed_candidate")

    @unittest.mock.patch('payout_helper.wallet_readonly_call')
    def test_real_wallet_payout_flag_does_not_cause_send(self, mock_wallet):
        """Command must refuse to perform any sends even if PEPEPOW_ENABLE_REAL_WALLET_PAYOUT is enabled."""
        import os
        os.environ["PEPEPOW_ENABLE_REAL_WALLET_PAYOUT"] = "true"
        os.environ["PEPEPOW_REAL_WALLET_PAYOUT_MAX_SENDS"] = "5"
        
        try:
            self._write_candidates([
                {
                    "candidateId": "candeligible000000000000000001",
                    "blockHash": "candeligible000000000000000001",
                    "height": 500,
                    "status": "ready_for_manual_review",
                    "payouts": [
                        {
                            "wallet": "PEPEPOW1WalletAddressTarget001",
                            "amount": 100.0,
                            "status": "pending_manual_payment"
                        }
                    ]
                }
            ])

            rc = payout_helper.payout_wallet_dry_run(self.candidates_path, self.output_path)
            self.assertEqual(rc, 0)

            called_methods = [call[0][0] for call in mock_wallet.call_args_list]
            for method in called_methods:
                self.assertNotIn(method, ["sendtoaddress", "sendmany", "walletpassphrase", "walletunlock"])
                
            with self.output_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                
            self.assertEqual(data["realSendEnabled"], False)
            self.assertEqual(data["items"][0]["rpcWouldSend"], False)
        finally:
            os.environ.pop("PEPEPOW_ENABLE_REAL_WALLET_PAYOUT", None)
            os.environ.pop("PEPEPOW_REAL_WALLET_PAYOUT_MAX_SENDS", None)



class WalletSendOnceTests(unittest.TestCase):
    """Focused tests for guarded one-shot wallet payout sends."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.candidates_path = self.tmp_path / "payout-candidates.json"
        self.actions_log = self.tmp_path / "payment-actions.jsonl"
        self.payments_snapshot = self.tmp_path / "payments-snapshot.json"
        self.output_path = self.tmp_path / "payout-wallet-send-once-result.json"
        self.candidate_id = "candeligible000000000000000001"
        self.wallet = "PEPEPOW1WalletAddressTarget001"
        self.amount = 100.0
        self._old_env = {k: os.environ.get(k) for k in [
            "PEPEPOW_ENABLE_REAL_WALLET_PAYOUT",
            "PEPEPOW_REAL_WALLET_PAYOUT_MAX_SENDS",
            "PEPEPOW_WALLET_CLI",
            "PEPEPOWD_RPC_URL",
            "PEPEPOWD_RPC_USER",
            "PEPEPOWD_RPC_PASSWORD",
        ]}
        for key in ["PEPEPOWD_RPC_URL", "PEPEPOWD_RPC_USER", "PEPEPOWD_RPC_PASSWORD"]:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp_dir.cleanup()

    def _write_candidate(self, *, amount=None, wallet=None, status="pending_manual_payment"):
        payout_amount = self.amount if amount is None else amount
        payout_wallet = self.wallet if wallet is None else wallet
        with self.candidates_path.open("w", encoding="utf-8") as f:
            json.dump({
                "items": [{
                    "candidateId": self.candidate_id,
                    "blockHash": self.candidate_id,
                    "height": 500,
                    "status": "ready_for_manual_review",
                    "payouts": [{
                        "wallet": payout_wallet,
                        "amount": payout_amount,
                        "status": status,
                    }],
                }]
            }, f)

    def _run_send_once(self, candidate_id=None, wallet=None, amount=None):
        return payout_helper.payout_wallet_send_once(
            self.candidates_path,
            self.actions_log,
            self.payments_snapshot,
            self.output_path,
            candidate_id or self.candidate_id,
            wallet or self.wallet,
            self.amount if amount is None else amount,
        )

    def _read_result(self):
        with self.output_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _enable_real_once(self):
        os.environ["PEPEPOW_ENABLE_REAL_WALLET_PAYOUT"] = "true"
        os.environ["PEPEPOW_REAL_WALLET_PAYOUT_MAX_SENDS"] = "1"


    def _install_noop_cli(self):
        cli_path = self.tmp_path / "PEPEPOW-cli"
        cli_path.write_text("#!/usr/bin/env python3\nprint('noop')\n", encoding="utf-8")
        cli_path.chmod(0o755)
        os.environ["PEPEPOW_WALLET_CLI"] = str(cli_path)
        return cli_path

    def test_flag_off_blocks_send_and_writes_artifact(self):
        os.environ["PEPEPOW_ENABLE_REAL_WALLET_PAYOUT"] = "false"
        os.environ["PEPEPOW_REAL_WALLET_PAYOUT_MAX_SENDS"] = "1"

        rc = self._run_send_once()
        self.assertEqual(rc, 0)
        data = self._read_result()
        self.assertEqual(data["status"], "blocked_real_wallet_payout_disabled")
        self.assertFalse(data["sendAttempted"])
        self.assertFalse(data["sendSent"])

    @unittest.mock.patch('payout_helper.load_env_vars')
    def test_invalid_max_sends_blocks_send(self, mock_env):
        for raw_max_sends in [None, "0", "2", "not-a-number"]:
            with self.subTest(raw_max_sends=raw_max_sends):
                env = {"PEPEPOW_ENABLE_REAL_WALLET_PAYOUT": "true"}
                if raw_max_sends is not None:
                    env["PEPEPOW_REAL_WALLET_PAYOUT_MAX_SENDS"] = raw_max_sends
                mock_env.return_value = env

                rc = self._run_send_once()
                self.assertEqual(rc, 0)
                self.assertEqual(self._read_result()["status"], "blocked_invalid_send_budget")

    def test_candidate_not_found_blocks_send(self):
        self._enable_real_once()
        self._write_candidate()

        rc = self._run_send_once(candidate_id="candmissing000000000000000001")
        self.assertEqual(rc, 0)
        self.assertEqual(self._read_result()["status"], "blocked_candidate_not_found")

    def test_amount_mismatch_blocks_send(self):
        self._enable_real_once()
        self._write_candidate(amount=101.0)

        rc = self._run_send_once()
        self.assertEqual(rc, 0)
        self.assertEqual(self._read_result()["status"], "blocked_amount_mismatch")

    def test_already_paid_blocks_send(self):
        self._enable_real_once()
        self._write_candidate()
        self.actions_log.write_text(json.dumps({
            "candidate_id": self.candidate_id,
            "wallet": self.wallet,
            "amount": self.amount,
            "txid": "txidalreadypaid000000000000001",
            "timestamp": "2026-06-07T00:00:00Z",
        }) + "\n", encoding="utf-8")

        rc = self._run_send_once()
        self.assertEqual(rc, 0)
        self.assertEqual(self._read_result()["status"], "blocked_already_paid")

    @unittest.mock.patch('payout_helper.wallet_readonly_call')
    def test_wallet_balance_unreadable_blocks_send(self, mock_wallet):
        self._enable_real_once()
        self._write_candidate()
        mock_wallet.return_value = None

        rc = self._run_send_once()
        self.assertEqual(rc, 0)
        data = self._read_result()
        self.assertEqual(data["status"], "blocked_wallet_balance_unreadable")
        self.assertFalse(data["sendAttempted"])
        self.assertFalse(data["sendSent"])

    @unittest.mock.patch('payout_helper.wallet_readonly_call')
    def test_insufficient_balance_blocks_send(self, mock_wallet):
        self._enable_real_once()
        self._write_candidate()
        mock_wallet.return_value = 50.0

        rc = self._run_send_once()
        self.assertEqual(rc, 0)
        self.assertEqual(self._read_result()["status"], "blocked_insufficient_balance")

    @unittest.mock.patch('payout_helper.wallet_readonly_call')
    def test_invalid_address_blocks_send(self, mock_wallet):
        self._enable_real_once()
        self._write_candidate()
        def side_effect(method, params):
            if method == "getbalance":
                return 500.0
            if method == "validateaddress":
                return {"isvalid": False}
            return None
        mock_wallet.side_effect = side_effect

        rc = self._run_send_once()
        self.assertEqual(rc, 0)
        self.assertEqual(self._read_result()["status"], "blocked_invalid_address")

    @unittest.mock.patch('payout_helper.wallet_readonly_call')
    def test_mocked_cli_send_records_payment_and_never_calls_forbidden_commands(self, mock_wallet):
        self._enable_real_once()
        self._write_candidate()
        def side_effect(method, params):
            if method == "getbalance":
                return 500.0
            if method == "validateaddress":
                return {"isvalid": True}
            return None
        mock_wallet.side_effect = side_effect

        cli_log = self.tmp_path / "cli-calls.log"
        cli_path = self.tmp_path / "PEPEPOW-cli"
        txid = "txidsendonce000000000000000001"
        cli_path.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib, sys\n"
            f"pathlib.Path({str(cli_log)!r}).write_text(' '.join(sys.argv[1:]) + '\\n', encoding='utf-8')\n"
            "if sys.argv[1] == 'sendtoaddress':\n"
            f"    print({txid!r})\n"
            "else:\n"
            "    raise SystemExit(2)\n",
            encoding="utf-8",
        )
        cli_path.chmod(0o755)
        os.environ["PEPEPOW_WALLET_CLI"] = str(cli_path)

        rc = self._run_send_once()
        self.assertEqual(rc, 0)
        data = self._read_result()
        self.assertEqual(data["status"], "sent_recorded")
        self.assertTrue(data["sendAttempted"])
        self.assertTrue(data["sendSent"])
        self.assertEqual(data["txid"], txid)

        calls = cli_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(calls, [f"sendtoaddress {self.wallet} {self.amount}"])
        forbidden = ["sendmany", "walletpassphrase", "walletunlock", "signrawtransaction", "createrawtransaction"]
        for call in calls:
            for method in forbidden:
                self.assertNotIn(method, call)

        with self.actions_log.open("r", encoding="utf-8") as f:
            actions = [json.loads(line) for line in f if line.strip()]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["candidate_id"], self.candidate_id)
        self.assertEqual(actions[0]["wallet"], self.wallet)
        self.assertAlmostEqual(actions[0]["amount"], self.amount)
        self.assertEqual(actions[0]["txid"], txid)


    @unittest.mock.patch('payout_helper.subprocess.run')
    def test_already_paid_does_not_call_sendtoaddress(self, mock_run):
        self._enable_real_once()
        self._write_candidate()
        self.actions_log.write_text(json.dumps({
            "candidate_id": self.candidate_id,
            "wallet": self.wallet,
            "amount": self.amount,
            "txid": "txidalreadypaid000000000000001",
            "timestamp": "2026-06-07T00:00:00Z",
        }) + "\n", encoding="utf-8")

        rc = self._run_send_once()
        self.assertEqual(rc, 0)
        self.assertEqual(self._read_result()["status"], "blocked_already_paid")
        mock_run.assert_not_called()

    @unittest.mock.patch('payout_helper.wallet_readonly_call')
    @unittest.mock.patch('payout_helper.subprocess.run')
    def test_repeated_invocation_cannot_send_twice_for_same_candidate_wallet(self, mock_run, mock_wallet):
        self._enable_real_once()
        self._write_candidate()
        self._install_noop_cli()
        mock_wallet.side_effect = lambda method, params: 500.0 if method == "getbalance" else {"isvalid": True}
        mock_run.return_value = unittest.mock.Mock(returncode=0, stdout="txidrepeat00000000000000000001\n")

        rc_first = self._run_send_once()
        rc_second = self._run_send_once()

        self.assertEqual(rc_first, 0)
        self.assertEqual(rc_second, 0)
        self.assertEqual(mock_run.call_count, 1)
        self.assertEqual(self._read_result()["status"], "blocked_already_paid")
        with self.actions_log.open("r", encoding="utf-8") as f:
            actions = [json.loads(line) for line in f if line.strip()]
        sent_actions = [action for action in actions if action.get("status") == "sent"]
        self.assertEqual(len(sent_actions), 1)

    @unittest.mock.patch('payout_helper.wallet_readonly_call')
    @unittest.mock.patch('payout_helper.subprocess.run')
    def test_failed_send_records_failed_action_and_not_successful_paid(self, mock_run, mock_wallet):
        self._enable_real_once()
        self._write_candidate()
        self._install_noop_cli()
        mock_wallet.side_effect = lambda method, params: 500.0 if method == "getbalance" else {"isvalid": True}
        mock_run.return_value = unittest.mock.Mock(returncode=1, stdout="", stderr="wallet rejected")

        rc = self._run_send_once()
        self.assertEqual(rc, 0)
        data = self._read_result()
        self.assertEqual(data["status"], "blocked_send_failed")
        self.assertTrue(data["sendAttempted"])
        self.assertFalse(data["sendSent"])
        with self.actions_log.open("r", encoding="utf-8") as f:
            actions = [json.loads(line) for line in f if line.strip()]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["status"], "failed")
        self.assertFalse(payout_helper.payment_already_recorded(self.actions_log, self.candidate_id, self.wallet))
        self.assertFalse(self.payments_snapshot.exists())

    @unittest.mock.patch('payout_helper.wallet_readonly_call')
    @unittest.mock.patch('payout_helper.subprocess.run')
    def test_successful_send_records_exactly_one_sent_action(self, mock_run, mock_wallet):
        self._enable_real_once()
        self._write_candidate()
        self._install_noop_cli()
        txid = "txidsuccess0000000000000000001"
        mock_wallet.side_effect = lambda method, params: 500.0 if method == "getbalance" else {"isvalid": True}
        mock_run.return_value = unittest.mock.Mock(returncode=0, stdout=f"{txid}\n")

        rc = self._run_send_once()
        self.assertEqual(rc, 0)
        self.assertEqual(self._read_result()["status"], "sent_recorded")
        with self.actions_log.open("r", encoding="utf-8") as f:
            actions = [json.loads(line) for line in f if line.strip()]
        sent_actions = [action for action in actions if action.get("status") == "sent"]
        self.assertEqual(len(sent_actions), 1)
        self.assertEqual(sent_actions[0]["txid"], txid)

    @unittest.mock.patch('payout_helper.wallet_readonly_call')
    @unittest.mock.patch('payout_helper.subprocess.run')
    def test_budget_exceeded_under_lock_blocks_send(self, mock_run, mock_wallet):
        self._enable_real_once()
        self._write_candidate()
        self._install_noop_cli()
        mock_wallet.side_effect = lambda method, params: 500.0 if method == "getbalance" else {"isvalid": True}
        old_load_env = payout_helper.load_env_vars
        calls = {"count": 0}

        def fake_load_env():
            calls["count"] += 1
            if calls["count"] >= 2:
                return {
                    "PEPEPOW_ENABLE_REAL_WALLET_PAYOUT": "true",
                    "PEPEPOW_REAL_WALLET_PAYOUT_MAX_SENDS": "2",
                    "PEPEPOW_WALLET_CLI": os.environ["PEPEPOW_WALLET_CLI"],
                }
            return old_load_env()

        try:
            payout_helper.load_env_vars = fake_load_env
            rc = self._run_send_once()
        finally:
            payout_helper.load_env_vars = old_load_env

        self.assertEqual(rc, 0)
        self.assertEqual(self._read_result()["status"], "blocked_budget_exceeded")
        mock_run.assert_not_called()


class WalletSendPreflightTests(unittest.TestCase):
    """Focused tests for guarded wallet payout send preflight."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.candidates_path = self.tmp_path / "payout-candidates.json"
        self.actions_log = self.tmp_path / "payment-actions.jsonl"
        self.output_path = self.tmp_path / "payout-wallet-send-preflight-result.json"
        self.candidate_id = "candeligible000000000000000001"
        self.wallet = "PEPEPOW1WalletAddressTarget001"
        self.amount = 100.0
        self._old_env = {k: os.environ.get(k) for k in [
            "PEPEPOW_ENABLE_REAL_WALLET_PAYOUT",
            "PEPEPOW_REAL_WALLET_PAYOUT_MAX_SENDS",
            "PEPEPOW_WALLET_CLI",
            "PEPEPOWD_RPC_URL",
            "PEPEPOWD_RPC_USER",
            "PEPEPOWD_RPC_PASSWORD",
        ]}
        for key in ["PEPEPOWD_RPC_URL", "PEPEPOWD_RPC_USER", "PEPEPOWD_RPC_PASSWORD"]:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp_dir.cleanup()

    def _write_candidate(self, *, amount=None, wallet=None, status="pending_manual_payment"):
        payout_amount = self.amount if amount is None else amount
        payout_wallet = self.wallet if wallet is None else wallet
        with self.candidates_path.open("w", encoding="utf-8") as f:
            json.dump({
                "items": [{
                    "candidateId": self.candidate_id,
                    "blockHash": self.candidate_id,
                    "height": 500,
                    "status": "ready_for_manual_review",
                    "payouts": [{
                        "wallet": payout_wallet,
                        "amount": payout_amount,
                        "status": status,
                    }],
                }]
            }, f)

    def _read_result(self):
        with self.output_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _enable_real_once(self):
        os.environ["PEPEPOW_ENABLE_REAL_WALLET_PAYOUT"] = "true"
        os.environ["PEPEPOW_REAL_WALLET_PAYOUT_MAX_SENDS"] = "1"

    def _run_preflight(self, candidate_id=None, wallet=None, amount=None):
        return payout_helper.payout_wallet_send_preflight(
            self.candidates_path,
            self.actions_log,
            self.output_path,
            candidate_id or self.candidate_id,
            wallet or self.wallet,
            self.amount if amount is None else amount,
        )

    @unittest.mock.patch('payout_helper.subprocess.run')
    @unittest.mock.patch('payout_helper.wallet_readonly_call')
    def test_preflight_ok_with_mocked_wallet_checks(self, mock_wallet, mock_run):
        self._enable_real_once()
        self._write_candidate()
        def side_effect(method, params):
            if method == "getbalance":
                return 500.0
            if method == "validateaddress":
                return {"isvalid": True}
            return None
        mock_wallet.side_effect = side_effect

        rc = self._run_preflight()
        self.assertEqual(rc, 0)
        data = self._read_result()
        self.assertEqual(data["mode"], "send_preflight")
        self.assertEqual(data["status"], "preflight_ok")
        self.assertTrue(data["sendWouldBeAllowed"])
        self.assertFalse(data["sendAttempted"])
        self.assertFalse(data["sendSent"])
        mock_run.assert_not_called()

    @unittest.mock.patch('payout_helper.subprocess.run')
    @unittest.mock.patch('payout_helper.wallet_readonly_call')
    def test_preflight_never_calls_sendtoaddress_when_real_flag_true(self, mock_wallet, mock_run):
        self._enable_real_once()
        self._write_candidate()
        def side_effect(method, params):
            if method == "getbalance":
                return 500.0
            if method == "validateaddress":
                return {"isvalid": True}
            return None
        mock_wallet.side_effect = side_effect

        rc = self._run_preflight()
        self.assertEqual(rc, 0)
        self.assertEqual(self._read_result()["status"], "preflight_ok")
        mock_run.assert_not_called()

    @unittest.mock.patch('payout_helper.load_env_vars')
    def test_preflight_invalid_budget_blocks(self, mock_env):
        for raw_max_sends in [None, "0", "2", "not-a-number"]:
            with self.subTest(raw_max_sends=raw_max_sends):
                env = {"PEPEPOW_ENABLE_REAL_WALLET_PAYOUT": "true"}
                if raw_max_sends is not None:
                    env["PEPEPOW_REAL_WALLET_PAYOUT_MAX_SENDS"] = raw_max_sends
                mock_env.return_value = env

                rc = self._run_preflight()
                self.assertEqual(rc, 0)
                data = self._read_result()
                self.assertEqual(data["status"], "blocked_invalid_send_budget")
                self.assertFalse(data["sendWouldBeAllowed"])
                self.assertFalse(data["sendAttempted"])
                self.assertFalse(data["sendSent"])

    def test_preflight_candidate_not_found_blocks(self):
        self._enable_real_once()
        self._write_candidate()

        rc = self._run_preflight(candidate_id="candmissing000000000000000001")
        self.assertEqual(rc, 0)
        self.assertEqual(self._read_result()["status"], "blocked_candidate_not_found")

    def test_preflight_wallet_not_in_candidate_blocks(self):
        self._enable_real_once()
        self._write_candidate()

        rc = self._run_preflight(wallet="PEPEPOW1WalletAddressTarget999")
        self.assertEqual(rc, 0)
        self.assertEqual(self._read_result()["status"], "blocked_wallet_not_in_candidate")

    def test_preflight_amount_mismatch_blocks(self):
        self._enable_real_once()
        self._write_candidate(amount=101.0)

        rc = self._run_preflight()
        self.assertEqual(rc, 0)
        self.assertEqual(self._read_result()["status"], "blocked_amount_mismatch")

    def test_preflight_already_paid_blocks(self):
        self._enable_real_once()
        self._write_candidate()
        self.actions_log.write_text(json.dumps({
            "candidate_id": self.candidate_id,
            "wallet": self.wallet,
            "amount": self.amount,
            "txid": "txidalreadypaid000000000000001",
            "timestamp": "2026-06-07T00:00:00Z",
        }) + "\n", encoding="utf-8")

        rc = self._run_preflight()
        self.assertEqual(rc, 0)
        self.assertEqual(self._read_result()["status"], "blocked_already_paid")

    @unittest.mock.patch('payout_helper.wallet_readonly_call')
    def test_preflight_unreadable_balance_blocks(self, mock_wallet):
        self._enable_real_once()
        self._write_candidate()
        mock_wallet.return_value = None

        rc = self._run_preflight()
        self.assertEqual(rc, 0)
        self.assertEqual(self._read_result()["status"], "blocked_wallet_balance_unreadable")

    @unittest.mock.patch('payout_helper.wallet_readonly_call')
    def test_preflight_insufficient_balance_blocks(self, mock_wallet):
        self._enable_real_once()
        self._write_candidate()
        mock_wallet.return_value = 50.0

        rc = self._run_preflight()
        self.assertEqual(rc, 0)
        self.assertEqual(self._read_result()["status"], "blocked_insufficient_balance")

    @unittest.mock.patch('payout_helper.wallet_readonly_call')
    def test_preflight_invalid_address_blocks(self, mock_wallet):
        self._enable_real_once()
        self._write_candidate()
        def side_effect(method, params):
            if method == "getbalance":
                return 500.0
            if method == "validateaddress":
                return {"isvalid": False}
            return None
        mock_wallet.side_effect = side_effect

        rc = self._run_preflight()
        self.assertEqual(rc, 0)
        self.assertEqual(self._read_result()["status"], "blocked_invalid_address")


if __name__ == "__main__":
    unittest.main()
