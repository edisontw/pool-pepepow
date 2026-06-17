#!/usr/bin/env python3
import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops" / "scripts"))
import payment_consistency_audit as audit


class PaymentConsistencyAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.actions = self.tmp_path / "payment-actions.jsonl"
        self.payments = self.tmp_path / "payments-snapshot.json"
        self.activity = self.tmp_path / "activity-snapshot.json"
        self.pool = self.tmp_path / "pool-snapshot.json"
        self.explorer = self.tmp_path / "explorer-transactions.json"
        self.pool.write_text(json.dumps({"network": {"height": 100}}), encoding="utf-8")
        self.activity.write_text(json.dumps({"miners": {}}), encoding="utf-8")
        self.payments.write_text(json.dumps({"items": []}), encoding="utf-8")

    def tearDown(self):
        self.tmp_dir.cleanup()

    def write_actions(self, rows):
        with self.actions.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")

    def write_payments(self, rows):
        self.payments.write_text(json.dumps({"items": rows}), encoding="utf-8")

    def write_activity_payment(self, wallet, rows):
        self.activity.write_text(
            json.dumps({"miners": {wallet: {"payments": rows}}}),
            encoding="utf-8",
        )

    def run_audit(self):
        return audit.audit(
            self.actions,
            self.payments,
            self.activity,
            self.pool,
            self.explorer,
            Decimal("0.00000001"),
        )

    def categories(self, result):
        return set(result["categories"])

    def test_ok_when_action_is_visible_in_payment_and_miner_sources(self):
        action = {
            "action": "manual_payment_recorded",
            "candidate_id": "cand1",
            "wallet": "walletA",
            "amount": 12.5,
            "txid": "tx1",
            "timestamp": "2026-06-13T00:00:00Z",
            "blockHeight": 90,
            "confirmations": 11,
        }
        self.write_actions([action])
        self.write_payments([action])

        result = self.run_audit()

        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["categories"], ["OK"])

    def test_missing_from_payments_and_miner_sources(self):
        self.write_actions(
            [
                {
                    "status": "sent",
                    "candidate_id": "cand1",
                    "wallet": "walletA",
                    "amount": 12.5,
                    "txid": "tx1",
                }
            ]
        )

        result = self.run_audit()

        self.assertIn(audit.MISSING_FROM_PAYMENTS_API, self.categories(result))
        self.assertIn(audit.MISSING_FROM_MINER_API, self.categories(result))

    def test_detects_duplicate_txid_and_exact_duplicate_inside_source(self):
        row = {
            "wallet": "walletA",
            "amount": 1.25,
            "txid": "tx1",
            "candidateHash": "cand1",
        }
        self.write_actions([])
        self.write_payments([row, dict(row)])

        result = self.run_audit()

        self.assertIn(audit.DUPLICATE_TXID, self.categories(result))
        exact_issues = [
            item for item in result["issues"]
            if item["category"] == audit.DUPLICATE_TXID
            and "wallet+txid+amount" in item["message"]
        ]
        self.assertTrue(exact_issues)

    def test_detects_amount_and_wallet_mismatches(self):
        self.write_actions(
            [
                {
                    "status": "sent",
                    "candidate_id": "cand1",
                    "wallet": "walletA",
                    "amount": 10,
                    "txid": "tx1",
                }
            ]
        )
        self.write_payments(
            [
                {
                    "candidateHash": "cand1",
                    "wallet": "walletA",
                    "amount": 10.1,
                    "txid": "tx1",
                },
                {
                    "candidateHash": "cand2",
                    "wallet": "walletB",
                    "amount": 10,
                    "txid": "tx1",
                },
            ]
        )

        result = self.run_audit()

        self.assertIn(audit.AMOUNT_MISMATCH, self.categories(result))
        self.assertIn(audit.WALLET_MISMATCH, self.categories(result))

    def test_detects_suspicious_height_and_confirmations(self):
        self.write_actions([])
        self.write_payments(
            [
                {
                    "wallet": "walletA",
                    "amount": 1,
                    "txid": "tx1",
                    "blockHeight": 90,
                    "confirmations": 99,
                }
            ]
        )

        result = self.run_audit()

        self.assertIn(audit.CONFIRMS_OR_HEIGHT_SUSPICIOUS, self.categories(result))

    def test_detects_stale_address_attribution_hints(self):
        self.write_actions(
            [
                {
                    "status": "sent",
                    "candidate_id": "cand1",
                    "wallet": "oldWallet",
                    "amount": 1,
                    "txid": "tx1",
                    "worker": "rig-a",
                    "timestamp": "2026-06-12T00:00:00Z",
                },
                {
                    "status": "sent",
                    "candidate_id": "cand2",
                    "wallet": "newWallet",
                    "amount": 2,
                    "txid": "tx2",
                    "worker": "rig-a",
                    "timestamp": "2026-06-13T00:00:00Z",
                },
            ]
        )
        self.write_payments(
            [
                {"candidateHash": "cand1", "wallet": "oldWallet", "amount": 1, "txid": "tx1"},
                {"candidateHash": "cand2", "wallet": "newWallet", "amount": 2, "txid": "tx2"},
            ]
        )

        result = self.run_audit()

        self.assertIn(audit.STALE_ADDRESS_ATTRIBUTION_HINT, self.categories(result))


if __name__ == "__main__":
    unittest.main()
