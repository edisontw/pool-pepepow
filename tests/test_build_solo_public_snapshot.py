from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "ops" / "scripts" / "build_solo_public_snapshot.py"
spec = importlib.util.spec_from_file_location("build_solo_public_snapshot", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(module)


class SoloPublicSnapshotTests(unittest.TestCase):
    def test_candidate_merge_keeps_chain_blocks_and_prefers_current(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            legacy = root / "legacy.json"
            current = root / "current.json"
            legacy.write_text(json.dumps({
                "accepted_candidates": [
                    {"candidate_hash": "old-block", "lifecycle_status": "confirmed", "confirmations": 500},
                    {"candidate_hash": "shared", "lifecycle_status": "confirmed", "confirmations": 100},
                    {"candidate_hash": "legacy-orphan", "lifecycle_status": "orphan"},
                ]
            }), encoding="utf-8")
            current.write_text(json.dumps({
                "accepted_candidates": [
                    {"candidate_hash": "shared", "lifecycle_status": "confirmed", "confirmations": 200},
                    {"candidate_hash": "new-block", "lifecycle_status": "immature", "confirmations": 20},
                    {"candidate_hash": "pending", "lifecycle_status": "candidate_recorded"},
                    {"candidate_hash": "current-orphan", "lifecycle_status": "orphan"},
                ]
            }), encoding="utf-8")

            rows = module.merge_candidates(current, legacy)
            by_hash = {row["candidate_hash"]: row for row in rows}
            self.assertEqual(set(by_hash), {"old-block", "shared", "new-block"})
            self.assertEqual(by_hash["shared"]["confirmations"], 200)

    def test_payment_merge_deduplicates_txid_and_prefers_current(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            legacy = root / "legacy-payments.json"
            current = root / "current-payments.json"
            legacy.write_text(json.dumps({
                "items": [
                    {"txid": "tx-old", "wallet": "A", "amount": 1},
                    {"txid": "tx-shared", "wallet": "B", "amount": 2, "status": "legacy"},
                ]
            }), encoding="utf-8")
            current.write_text(json.dumps({
                "items": [
                    {"txid": "tx-shared", "wallet": "B", "amount": 2, "status": "current"},
                    {"txid": "tx-new", "wallet": "C", "amount": 3},
                ]
            }), encoding="utf-8")

            rows = module.merge_payments(current, legacy)
            by_txid = {row["txid"]: row for row in rows}
            self.assertEqual(set(by_txid), {"tx-old", "tx-shared", "tx-new"})
            self.assertEqual(by_txid["tx-shared"]["status"], "current")


if __name__ == "__main__":
    unittest.main()
