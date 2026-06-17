#!/usr/bin/env python3
import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops" / "scripts"))
import operator_status_snapshot as status_snapshot
import payment_consistency_audit


class OperatorStatusSnapshotTests(unittest.TestCase):
    def test_payment_audit_rewrite_hint_only_is_warning(self):
        item = status_snapshot.payment_audit_item(
            {
                "status": "warning",
                "categories": [payment_consistency_audit.DUPLICATE_ACTION_TXID_REWRITE_HINT],
                "issues": [{"category": payment_consistency_audit.DUPLICATE_ACTION_TXID_REWRITE_HINT}],
            }
        )

        self.assertEqual(item["status"], "warning")
        self.assertEqual(item["message"], "Payment records need review")
        self.assertNotIn("issues", item)

    def test_payment_audit_other_issue_is_error(self):
        item = status_snapshot.payment_audit_item(
            {
                "status": "warning",
                "categories": [payment_consistency_audit.MISSING_FROM_PAYMENTS_API],
            }
        )

        self.assertEqual(item["status"], "error")
        self.assertEqual(item["message"], "Payment records need review")

    def test_build_operator_status_exposes_only_public_fields(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            now = "2999-01-01T00:00:00Z"
            for filename in (
                "pool-snapshot.json",
                "activity-snapshot.json",
                "rounds-snapshot.json",
                "payments-snapshot.json",
                "accepted-candidates.json",
            ):
                payload = {"generatedAt": now}
                if filename == "pool-snapshot.json":
                    payload["network"] = {"height": 10}
                if filename == "activity-snapshot.json":
                    payload["miners"] = {}
                if filename == "rounds-snapshot.json":
                    payload["rounds"] = []
                if filename == "payments-snapshot.json":
                    payload["items"] = []
                if filename == "accepted-candidates.json":
                    payload["accepted_candidates"] = []
                (root / filename).write_text(json.dumps(payload), encoding="utf-8")
            (root / "pool-wallet-watchdog.json").write_text(
                json.dumps({"generatedAt": now, "status": "ok", "summary": "internal"}),
                encoding="utf-8",
            )

            args = argparse.Namespace(
                runtime_dir=str(root),
                output=str(root / "operator-status.json"),
                activity_snapshot=str(root / "activity-snapshot.json"),
                rounds_snapshot=str(root / "rounds-snapshot.json"),
                payments_snapshot=str(root / "payments-snapshot.json"),
                accepted_candidates=str(root / "accepted-candidates.json"),
                share_log=str(root / "share-events.jsonl"),
                watchdog_snapshot=str(root / "pool-wallet-watchdog.json"),
                launch_env=str(root / "launch.env"),
                pool_snapshot=str(root / "pool-snapshot.json"),
                actions_log=str(root / "payment-actions.jsonl"),
                explorer_transactions=str(root / "explorer-transactions.json"),
                tolerance=str(payment_consistency_audit.DEFAULT_TOLERANCE),
                snapshot_stale_seconds=999999999.0,
            )

            payload = status_snapshot.build_operator_status(args)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual([item["key"] for item in payload["items"]], ["pool_health", "wallet_watchdog", "payment_audit"])
        for item in payload["items"]:
            self.assertEqual(set(item), {"key", "label", "status", "message"})


if __name__ == "__main__":
    unittest.main()
