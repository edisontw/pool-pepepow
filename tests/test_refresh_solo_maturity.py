from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "ops" / "scripts" / "refresh_solo_maturity.py"
SPEC = importlib.util.spec_from_file_location("refresh_solo_maturity", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RefreshSoloMaturityTests(unittest.TestCase):
    def test_chain_match_found_becomes_confirmed_from_height(self):
        payload = {
            "accepted_candidates": [
                {
                    "candidate_hash": "abc",
                    "matched_height": 900,
                    "lifecycle_status": "chain_match_found",
                    "confirmations": None,
                    "maturity_label": "immature",
                }
            ]
        }

        changed = MODULE.refresh_maturity(payload, 1050)

        self.assertEqual(changed, 1)
        item = payload["accepted_candidates"][0]
        self.assertEqual(item["confirmations"], 151)
        self.assertEqual(item["lifecycle_status"], "confirmed")
        self.assertEqual(item["maturity_label"], "mature")

    def test_confirmations_do_not_regress_on_stale_height(self):
        payload = {
            "accepted_candidates": [
                {
                    "candidate_hash": "abc",
                    "matched_height": 900,
                    "lifecycle_status": "confirmed",
                    "confirmations": 250,
                    "maturity_label": "mature",
                }
            ]
        }

        MODULE.refresh_maturity(payload, 1000)

        item = payload["accepted_candidates"][0]
        self.assertEqual(item["confirmations"], 250)
        self.assertEqual(item["lifecycle_status"], "confirmed")

    def test_orphan_is_never_promoted(self):
        payload = {
            "accepted_candidates": [
                {
                    "candidate_hash": "abc",
                    "matched_height": 900,
                    "lifecycle_status": "orphan",
                    "confirmations": None,
                }
            ]
        }

        changed = MODULE.refresh_maturity(payload, 1050)

        self.assertEqual(changed, 0)
        self.assertEqual(payload["accepted_candidates"][0]["lifecycle_status"], "orphan")

    def test_main_uses_single_rpc_height_fallback_when_snapshot_height_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            accepted = root / "accepted-candidates.json"
            snapshot = root / "pool-snapshot.json"
            accepted.write_text(
                json.dumps(
                    {
                        "accepted_candidates": [
                            {
                                "candidate_hash": "abc",
                                "matched_height": 900,
                                "lifecycle_status": "chain_match_found",
                                "confirmations": None,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            snapshot.write_text(json.dumps({"network": {"height": 0}}), encoding="utf-8")

            with mock.patch.object(MODULE, "_rpc_height", return_value=1050), mock.patch(
                "sys.argv",
                [
                    "refresh_solo_maturity.py",
                    "--accepted-candidates",
                    str(accepted),
                    "--pool-snapshot",
                    str(snapshot),
                ],
            ):
                rc = MODULE.main()

            self.assertEqual(rc, 0)
            item = json.loads(accepted.read_text(encoding="utf-8"))["accepted_candidates"][0]
            self.assertEqual(item["confirmations"], 151)
            self.assertEqual(item["lifecycle_status"], "confirmed")


if __name__ == "__main__":
    unittest.main()
