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


if __name__ == "__main__":
    unittest.main()
