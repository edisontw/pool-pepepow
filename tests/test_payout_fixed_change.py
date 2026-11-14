#!/usr/bin/env python3
"""Offline regression tests: fixed payout change must never escape the pool wallet."""

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops" / "scripts"))
from payout_fixed_change import FixedChangeError, send_fixed_change


RECIPIENT = "PVKL38CAZxKX3tNczQCL9gN94i3SJ2LeNd"
POOL = "PKTwq3nHNxwcVgDX4QwVxQGX5DYjJB8nho"
RANDOM_CHANGE = "PAnotherWalletOwnedChangeAddress"
INPUT_TXID = "a" * 64
SENT_TXID = "b" * 64
VIN = [{"txid": INPUT_TXID, "vout": 0, "sequence": 4294967295}]


def out(address, value):
    return {"value": value, "scriptPubKey": {"addresses": [address]}}


def decoded(outputs, txid=None):
    result = {"version": 1, "locktime": 0, "vin": VIN, "vout": outputs}
    if txid:
        result["txid"] = txid
    return result


class FakeCli:
    def __init__(self, *, foreign_change=False, owner=True, fee="0.001", complete=True,
                 broadcast_timeout=False, no_change=False):
        self.calls = []
        self.foreign_change = foreign_change
        self.owner = owner
        self.fee = fee
        self.complete = complete
        self.broadcast_timeout = broadcast_timeout
        self.no_change = no_change

    def __call__(self, argv, **kwargs):
        method = argv[1]
        self.calls.append(argv)
        if method == "validateaddress":
            result = {"isvalid": True, "ismine": self.owner if argv[2] == POOL else False}
        elif method == "createrawtransaction":
            result = "funding-seed" if argv[2] == "[]" else "rebuilt-raw"
        elif method == "fundrawtransaction":
            result = {"hex": "funded-raw", "fee": self.fee, "changepos": -1 if self.no_change else 1}
        elif method == "decoderawtransaction":
            if argv[2] == "funded-raw":
                outputs = [out(RECIPIENT, 50)] if self.no_change else [
                    out(RECIPIENT, 50), out(RANDOM_CHANGE, 49.999)
                ]
                result = decoded(outputs)
            else:
                outputs = [out(RECIPIENT, 50)] if self.no_change else [
                    out(RECIPIENT, 50),
                    out(RANDOM_CHANGE if self.foreign_change else POOL, 49.999),
                ]
                result = decoded(outputs, SENT_TXID if argv[2] == "signed-raw" else None)
        elif method == "signrawtransaction":
            result = {"hex": "signed-raw", "complete": self.complete}
        elif method == "sendrawtransaction":
            if self.broadcast_timeout:
                raise subprocess.TimeoutExpired(argv, 15)
            return subprocess.CompletedProcess(argv, 0, SENT_TXID + "\n", "")
        else:
            raise AssertionError(method)
        stdout = result if isinstance(result, str) else json.dumps(result)
        return subprocess.CompletedProcess(argv, 0, stdout + "\n", "")


class FixedChangePayoutTests(unittest.TestCase):
    def run_fake(self, fake):
        with patch("payout_fixed_change.subprocess.run", side_effect=fake):
            return send_fixed_change("/bin/PEPEPOW-cli", RECIPIENT, "50", POOL)

    def test_funded_change_is_replaced_and_signed_before_broadcast(self):
        fake = FakeCli()
        result = self.run_fake(fake)
        self.assertEqual(result.stdout.strip(), SENT_TXID)
        commands = [call[1] for call in fake.calls]
        self.assertEqual(commands[-1], "sendrawtransaction")
        rebuild = next(call for call in fake.calls if call[1] == "createrawtransaction" and call[2] != "[]")
        self.assertEqual(json.loads(rebuild[3]), {RECIPIENT: "50", POOL: "49.999"})
        self.assertNotIn("sendtoaddress", commands)

    def test_foreign_change_output_never_broadcasts(self):
        fake = FakeCli(foreign_change=True)
        with self.assertRaises(FixedChangeError):
            self.run_fake(fake)
        self.assertNotIn("sendrawtransaction", [call[1] for call in fake.calls])

    def test_pool_address_must_be_spendable_by_wallet(self):
        fake = FakeCli(owner=False)
        with self.assertRaises(FixedChangeError):
            self.run_fake(fake)
        self.assertNotIn("fundrawtransaction", [call[1] for call in fake.calls])

    def test_excessive_funding_fee_fails_closed(self):
        fake = FakeCli(fee="9.0")
        with self.assertRaises(FixedChangeError):
            self.run_fake(fake)
        self.assertNotIn("sendrawtransaction", [call[1] for call in fake.calls])

    def test_incomplete_signature_fails_closed(self):
        fake = FakeCli(complete=False)
        with self.assertRaises(FixedChangeError):
            self.run_fake(fake)
        self.assertNotIn("sendrawtransaction", [call[1] for call in fake.calls])

    def test_no_change_transaction_keeps_original_funded_hex(self):
        fake = FakeCli(no_change=True)
        result = self.run_fake(fake)
        self.assertEqual(result.stdout.strip(), SENT_TXID)
        calls = [call for call in fake.calls if call[1] == "createrawtransaction"]
        self.assertEqual(len(calls), 1)

    def test_ambiguous_broadcast_cannot_retry_as_definite_failure(self):
        fake = FakeCli(broadcast_timeout=True)
        with self.assertRaises(TimeoutError):
            self.run_fake(fake)
        self.assertEqual([call[1] for call in fake.calls].count("sendrawtransaction"), 1)

    def test_same_recipient_as_change_fails_closed(self):
        fake = FakeCli()
        with patch("payout_fixed_change.subprocess.run", side_effect=fake):
            with self.assertRaises(FixedChangeError):
                send_fixed_change("/bin/PEPEPOW-cli", POOL, "50", POOL)
        self.assertEqual(fake.calls, [])


    def test_uncertain_raw_broadcast_is_not_cleared_by_missing_wallet_history(self):
        import tempfile
        import payout_helper
        with tempfile.TemporaryDirectory() as directory:
            actions = Path(directory) / "payment-actions.jsonl"
            payout_helper.append_payment_action(actions, {
                "action": "payment_intent",
                "intent_id": "intent:raw:1",
                "candidate_id": "height-1",
                "wallet": RECIPIENT,
                "amount": 50,
                "status": "intent",
                "payoutMode": "fixed_change",
            })
            payout_helper.append_payment_action(actions, {
                "action": "payment_intent_ambiguous",
                "intent_id": "intent:raw:1",
                "candidate_id": "height-1",
                "wallet": RECIPIENT,
                "amount": 50,
                "status": "ambiguous",
                "payoutMode": "fixed_change",
            })
            with patch("payout_helper.wallet_readonly_call", return_value=[]):
                summary = payout_helper.reconcile_unresolved_payment_intents(actions)
            self.assertEqual(summary["pendingCount"], 1)
            self.assertEqual(summary["reconciledFailed"], 0)
            self.assertEqual(len(payout_helper.get_unresolved_payment_intents(actions)), 1)


if __name__ == "__main__":
    unittest.main()
