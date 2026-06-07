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
        self.assertEqual(item_map["cand_zero_weight"]["reason"], "zero_total_round_weight")

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

            # 2. Block orphaned via daemon RPC confirmations
            c2 = item_map["hash_orphan_via_daemon_rpc"]
            self.assertEqual(c2["status"], "blocked")
            self.assertEqual(c2["reason"], "orphan_block")

            # 3. Block orphaned via rounds snapshot status
            c3 = item_map["hash_orphan_via_rounds_snapshot"]
            self.assertEqual(c3["status"], "blocked")
            self.assertEqual(c3["reason"], "orphan_block")

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
        self.assertIn("carry_items: 2", output)
        self.assertIn("carry_total_amount: 15.5", output)
        self.assertIn("wallets_with_carry: ['walletB', 'walletC']", output)
        self.assertIn("candidate_payouts_with_carry: 1", output)
        self.assertIn("candidate_carry_applied_amount: 60.0", output)
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
        self.assertIn("carry_items: 0", output)
        self.assertIn("carry_total_amount: 0.0", output)
        self.assertIn("wallets_with_carry: []", output)
        self.assertIn("candidate_payouts_with_carry: 0", output)
        self.assertIn("candidate_carry_applied_amount: 0.0", output)
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
        self.assertIn("carry_items: 0", output)
        self.assertIn("carry_total_amount: 0.0", output)
        self.assertIn("wallets_with_carry: []", output)
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


if __name__ == "__main__":
    unittest.main()


