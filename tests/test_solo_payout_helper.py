from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "ops" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import solo_payout_helper


class SoloPayoutHelperTests(unittest.TestCase):
    def test_build_solo_payout_candidate_fee_deduction(self):
        record = {
            "candidate_hash": "c100",
            "matched_height": 500,
            "submit_timestamp": "2026-08-11T12:00:00Z",
            "lifecycle_status": "confirmed",
            "confirmations": 105,
            "wallet": "Pabcdef12345",
            "worker": "rig01",
            "mining_mode": "solo",
        }
        coinbase_data = {
            "minerRewardAmount": 6500.0,
            "coinbaseTxid": "tx100",
            "coinbaseMatchesExpectedPoolWallet": True,
        }

        cand = solo_payout_helper.build_solo_payout_candidate(record, coinbase_data, solo_fee_percent=1.0)
        self.assertEqual(cand["candidateId"], "solo:c100")
        self.assertEqual(cand["grossReward"], 6500.0)
        self.assertEqual(cand["soloFeePercent"], 1.0)
        self.assertEqual(cand["soloFeeAmount"], 65.0)
        self.assertEqual(cand["netReward"], 6435.0)
        self.assertEqual(cand["finderWallet"], "Pabcdef12345")
        self.assertEqual(cand["finderWorker"], "rig01")
        self.assertEqual(len(cand["payouts"]), 1)
        self.assertEqual(cand["payouts"][0]["wallet"], "Pabcdef12345")
        self.assertEqual(cand["payouts"][0]["amount"], 6435.0)
        self.assertEqual(cand["payouts"][0]["status"], "pending_manual_payment")

    def test_evaluate_solo_eligibility(self):
        base_cand = {
            "candidateId": "solo:c100",
            "miningMode": "solo",
            "lifecycleStatus": "confirmed",
            "confirmations": 110,
            "finderWallet": "Pabcdef12345",
            "netReward": 6435.0,
            "coinbaseMatchesExpectedPoolWallet": True,
            "payouts": [{"wallet": "Pabcdef12345", "amount": 6435.0}],
        }

        # Valid candidate
        ok, reason = solo_payout_helper.evaluate_solo_eligibility(base_cand, min_confirmations=101)
        self.assertTrue(ok)
        self.assertIsNone(reason)

        # Immature (under 101 confirmations)
        cand_immature = dict(base_cand, confirmations=50)
        ok, reason = solo_payout_helper.evaluate_solo_eligibility(cand_immature, min_confirmations=101)
        self.assertFalse(ok)
        self.assertIn("insufficient_confirmations", reason)

        # Orphan status
        cand_orphan = dict(base_cand, lifecycleStatus="orphan")
        ok, reason = solo_payout_helper.evaluate_solo_eligibility(cand_orphan, min_confirmations=101)
        self.assertFalse(ok)
        self.assertEqual(reason, "status_orphan")

        # Coinbase mismatch
        cand_mismatch = dict(base_cand, coinbaseMatchesExpectedPoolWallet=False)
        ok, reason = solo_payout_helper.evaluate_solo_eligibility(cand_mismatch, min_confirmations=101)
        self.assertFalse(ok)
        self.assertEqual(reason, "blocked_coinbase_reward_mismatch")

        # Missing finder wallet
        cand_no_wallet = dict(base_cand, finderWallet="")
        ok, reason = solo_payout_helper.evaluate_solo_eligibility(cand_no_wallet, min_confirmations=101)
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_finder_wallet")

        # Already paid
        paid_pairs = {("solo:c100", "Pabcdef12345")}
        ok, reason = solo_payout_helper.evaluate_solo_eligibility(base_cand, paid_pairs=paid_pairs, min_confirmations=101)
        self.assertFalse(ok)
        self.assertEqual(reason, "blocked_already_paid")

    def test_generate_solo_payout_candidates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            accepted_path = Path(tmpdir) / "accepted-candidates.json"
            output_path = Path(tmpdir) / "solo-payout-candidates.json"

            accepted_data = {
                "accepted_candidates": [
                    {
                        "candidate_hash": "solo_block_1",
                        "matched_height": 1000,
                        "lifecycle_status": "confirmed",
                        "confirmations": 150,
                        "wallet": "Pfinder001",
                        "worker": "rig01",
                        "mining_mode": "solo",
                    },
                    {
                        "candidate_hash": "pool_block_1",
                        "matched_height": 1001,
                        "lifecycle_status": "confirmed",
                        "confirmations": 149,
                        "wallet": "Ppool001",
                        "worker": "rig02",
                        "mining_mode": "pool",
                    },
                ]
            }
            accepted_path.write_text(json.dumps(accepted_data), encoding="utf-8")

            mock_coinbase = {
                "solo_block_1": {
                    "minerRewardAmount": 6500.0,
                    "coinbaseTxid": "txsolo1",
                    "coinbaseMatchesExpectedPoolWallet": True,
                }
            }

            res = solo_payout_helper.generate_solo_payout_candidates(
                accepted_path,
                output_path,
                solo_fee_percent=1.0,
                min_confirmations=101,
                mock_coinbase_data=mock_coinbase,
            )
            cands = res["solo_payout_candidates"]
            self.assertEqual(len(cands), 1)
            self.assertEqual(cands[0]["candidateHash"], "solo_block_1")
            self.assertEqual(cands[0]["netReward"], 6435.0)
            self.assertTrue(cands[0]["eligibleForPayout"])

            # Shared aggregate sender validates sources through the standard
            # items collection and accepts pending_manual_payment rows.
            self.assertEqual(res["items"], cands)
            self.assertEqual(res["items"][0]["candidateId"], "solo:solo_block_1")
            self.assertEqual(
                res["items"][0]["payouts"][0]["status"],
                "pending_manual_payment",
            )
            persisted = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["items"], persisted["solo_payout_candidates"])

    def test_operational_solo_auto_payout_and_isolation(self):
        import payout_helper
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            solo_cands_path = tmp_path / "solo-payout-candidates.json"
            solo_actions_path = tmp_path / "solo-payment-actions.jsonl"
            solo_payments_path = tmp_path / "solo-payments-snapshot.json"
            solo_out_path = tmp_path / "solo-auto-payout-result.json"

            # Create 3 SOLO candidates:
            # 1. Confirmed unpaid (solocand1)
            # 2. Confirmed already paid (solocand2)
            # 3. Immature candidate (solocand3)
            solo_data = {
                "solo_payout_candidates": [
                    {
                        "candidateId": "solo:solocand1",
                        "candidateHash": "solocand1",
                        "miningMode": "solo",
                        "lifecycleStatus": "confirmed",
                        "confirmations": 110,
                        "coinbaseMatchesExpectedPoolWallet": True,
                        "finderWallet": "PwalletA111",
                        "finderWorker": "rig1",
                        "grossReward": 5000.0,
                        "soloFeePercent": 1.0,
                        "soloFeeAmount": 50.0,
                        "netReward": 4950.0,
                        "status": "ready",
                        "weightMode": "solo_finder",
                        "payouts": [{"wallet": "PwalletA111", "amount": 4950.0, "status": "ready"}],
                    },
                    {
                        "candidateId": "solo:solocand2",
                        "candidateHash": "solocand2",
                        "miningMode": "solo",
                        "lifecycleStatus": "confirmed",
                        "confirmations": 120,
                        "coinbaseMatchesExpectedPoolWallet": True,
                        "finderWallet": "PwalletB222",
                        "finderWorker": "rig2",
                        "grossReward": 5000.0,
                        "soloFeePercent": 1.0,
                        "soloFeeAmount": 50.0,
                        "netReward": 4950.0,
                        "status": "ready",
                        "weightMode": "solo_finder",
                        "payouts": [{"wallet": "PwalletB222", "amount": 4950.0, "status": "ready"}],
                    },
                    {
                        "candidateId": "solo:solocand3",
                        "candidateHash": "solocand3",
                        "miningMode": "solo",
                        "lifecycleStatus": "immature",
                        "confirmations": 40,
                        "coinbaseMatchesExpectedPoolWallet": True,
                        "finderWallet": "PwalletC333",
                        "finderWorker": "rig3",
                        "grossReward": 5000.0,
                        "soloFeePercent": 1.0,
                        "soloFeeAmount": 50.0,
                        "netReward": 4950.0,
                        "status": "ready",
                        "weightMode": "solo_finder",
                        "payouts": [{"wallet": "PwalletC333", "amount": 4950.0, "status": "ready"}],
                    },
                ]
            }
            solo_cands_path.write_text(json.dumps(solo_data), encoding="utf-8")

            # Mark solocand2 as already paid in actions log
            paid_action = {
                "action": "sent",
                "candidateId": "solo:solocand2",
                "wallet": "PwalletB222",
                "amount": 4950.0,
                "txid": "txid_already_paid_solocand2",
                "timestamp": "2026-08-11T12:00:00Z",
            }
            solo_actions_path.write_text(json.dumps(paid_action) + "\n", encoding="utf-8")
            solo_payments_path.write_text(json.dumps({"items": []}), encoding="utf-8")

            def fake_send_aggregate(*args, **kwargs):
                actions_log_p = args[1] if len(args) > 1 else kwargs.get("actions_log_path")
                out_p = args[3] if len(args) > 3 else kwargs.get("output_path")
                wallet = args[4] if len(args) > 4 else kwargs.get("wallet")
                total_amount = args[5] if len(args) > 5 else kwargs.get("total_amount")
                source_ids = args[6] if len(args) > 6 else kwargs.get("source_ids")
                record = {
                    "action": "sent",
                    "candidateId": source_ids[0] if source_ids else "",
                    "wallet": wallet,
                    "amount": float(total_amount),
                    "txid": "txid_newly_sent_solocand1",
                    "timestamp": "2026-08-11T15:00:00Z",
                }
                with actions_log_p.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")

                res = {
                    "status": "sent_recorded",
                    "sendSent": True,
                    "sendAttempted": True,
                    "txid": "txid_newly_sent_solocand1",
                    "wallet": wallet,
                    "totalAmount": str(total_amount),
                    "sourceCandidateIds": source_ids,
                }
                out_p.write_text(json.dumps(res), encoding="utf-8")
                return 0

            with patch("payout_helper.payout_wallet_send_aggregated_once", side_effect=fake_send_aggregate):
                with patch.dict("os.environ", {"PEPEPOW_ENABLE_REAL_WALLET_PAYOUT": "true", "PEPEPOW_AUTO_PAYOUT_ALLOW_ANY_WALLET": "true"}):
                    res_code = payout_helper.auto_payout_once(
                        solo_cands_path,
                        solo_actions_path,
                        solo_payments_path,
                        solo_out_path,
                        max_sends=5,
                        min_payout=0.00001,
                    )

            out_data = json.loads(solo_out_path.read_text(encoding="utf-8"))
            self.assertEqual(out_data["status"], "ok")

            # Verify solocand1 was sent
            self.assertEqual(out_data["sentCount"], 1)
            # Verify solocand2 (already paid) and solocand3 (immature) were skipped
            skipped_reasons = {item.get("candidateId"): item.get("reason") for item in out_data.get("items", []) if item.get("action") == "skipped"}
            self.assertEqual(skipped_reasons.get("solo:solocand2"), "blocked_already_paid")
            self.assertEqual(skipped_reasons.get("solo:solocand3"), "lifecycle_status_immature")

            # Verify payment action persisted to solo_actions_path
            actions_text = solo_actions_path.read_text(encoding="utf-8")
            self.assertIn("txid_newly_sent_solocand1", actions_text)
            self.assertIn("PwalletA111", actions_text)

            # Re-running auto_payout_once on next cycle: both solocand1 and solocand2 should now be skipped
            with patch("payout_helper.payout_wallet_send_aggregated_once", side_effect=fake_send_aggregate) as mock_send_again:
                with patch.dict("os.environ", {"PEPEPOW_ENABLE_REAL_WALLET_PAYOUT": "true", "PEPEPOW_AUTO_PAYOUT_ALLOW_ANY_WALLET": "true"}):
                    payout_helper.auto_payout_once(
                        solo_cands_path,
                        solo_actions_path,
                        solo_payments_path,
                        solo_out_path,
                        max_sends=5,
                        min_payout=0.00001,
                    )
                mock_send_again.assert_not_called()

            out_data2 = json.loads(solo_out_path.read_text(encoding="utf-8"))
            self.assertEqual(out_data2["sentCount"], 0)


if __name__ == "__main__":
    unittest.main()