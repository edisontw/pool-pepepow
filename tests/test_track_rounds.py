from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

# Add ops/scripts to python path
SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "ops" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import track_rounds  # noqa: E402


class TrackRoundsTests(unittest.TestCase):
    def test_round_safety_and_attribution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cand_path = Path(tmpdir) / "accepted-candidates.json"
            share_log = Path(tmpdir) / "share-events.jsonl"
            act_path = Path(tmpdir) / "activity-snapshot.json"
            out_path = Path(tmpdir) / "rounds-snapshot.json"

            # Set up accepted candidates mapping blocks to rounds
            # Candidates sorted chronologically: c1 (height 100), c2 (height 101), c3 (height 102), c4 (height 103)
            candidates_data = {
                "accepted_candidates": [
                    {
                        "candidate_hash": "hash-orphan",
                        "lifecycle_status": "orphan",
                        "matched_height": 100,
                        "submit_timestamp": "2026-06-05T12:00:00Z",
                        "confirmations": 0,
                    },
                    {
                        "candidate_hash": "hash-chain-match",
                        "lifecycle_status": "chain_match_found",
                        "matched_height": 101,
                        "submit_timestamp": "2026-06-05T12:05:00Z",
                        "confirmations": None,
                    },
                    {
                        "candidate_hash": "hash-immature",
                        "lifecycle_status": "immature",
                        "matched_height": 102,
                        "submit_timestamp": "2026-06-05T12:10:00Z",
                        "confirmations": 5,
                    },
                    {
                        "candidate_hash": "hash-confirmed",
                        "lifecycle_status": "confirmed",
                        "matched_height": 103,
                        "submit_timestamp": "2026-06-05T12:15:00Z",
                        "confirmations": 105,
                    },
                ]
            }
            with cand_path.open("w", encoding="utf-8") as f:
                json.dump(candidates_data, f)

            # Set up share events
            shares = [
                # Share for orphan (before or at 12:00:00Z)
                {
                    "wallet": "walletA",
                    "timestamp": "2026-06-05T11:59:00Z",
                    "accepted": True,
                    "submit": {"difficulty": 0.5},
                },
                # Share for chain-match (between 12:00:00Z and 12:05:00Z)
                {
                    "wallet": "walletB",
                    "timestamp": "2026-06-05T12:02:00Z",
                    "accepted": True,
                    "submit": {"difficulty": 1.0},
                },
                # Malformed share: missing wallet
                {
                    "timestamp": "2026-06-05T12:03:00Z",
                    "accepted": True,
                    "submit": {"difficulty": 10.0},
                },
                # Rejected share
                {
                    "wallet": "walletB",
                    "timestamp": "2026-06-05T12:04:00Z",
                    "accepted": False,
                    "submit": {"difficulty": 10.0},
                },
                # Low-difficulty share (min difficulty defaults to 0.1 in our test, let's say 0.005)
                {
                    "wallet": "walletB",
                    "timestamp": "2026-06-05T12:04:30Z",
                    "accepted": True,
                    "submit": {"difficulty": 0.05},  # low diff
                },
                # Valid share for immature (between 12:05:00Z and 12:10:00Z)
                {
                    "wallet": "walletA",
                    "timestamp": "2026-06-05T12:07:00Z",
                    "accepted": True,
                    "submit": {"difficulty": 2.0},
                },
                # Valid share for confirmed (between 12:10:00Z and 12:15:00Z)
                {
                    "wallet": "walletC",
                    "timestamp": "2026-06-05T12:12:00Z",
                    "accepted": True,
                    "submit": {"difficulty": 3.0},
                },
            ]
            with share_log.open("w", encoding="utf-8") as f:
                for s in shares:
                    f.write(json.dumps(s) + "\n")

            # Set up activity snapshot
            act_data = {"meta": {"assumedShareDifficulty": 0.1}}
            with act_path.open("w", encoding="utf-8") as f:
                json.dump(act_data, f)

            # Run tracking logic
            orig_argv = sys.argv
            sys.argv = [
                "track_rounds.py",
                "--accepted-candidates",
                str(cand_path),
                "--share-log",
                str(share_log),
                "--activity-snapshot",
                str(act_path),
                "--output",
                str(out_path),
            ]
            try:
                exit_code = track_rounds.main()
                self.assertEqual(exit_code, 0)
            finally:
                sys.argv = orig_argv

            self.assertTrue(out_path.exists())
            data = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertIn("updated_at", data)
            rounds = data["rounds"]
            self.assertEqual(len(rounds), 4)

            # Orphan round checks
            r0 = rounds[0]
            self.assertEqual(r0["candidate_hash"], "hash-orphan")
            self.assertEqual(r0["status"], "orphan")
            self.assertEqual(r0["payable"], False)
            self.assertNotIn("balance", r0)
            self.assertEqual(r0["shares"].get("walletA"), 0.5)

            # chain_match_found round checks
            r1 = rounds[1]
            self.assertEqual(r1["candidate_hash"], "hash-chain-match")
            self.assertEqual(r1["status"], "chain_match_found")
            self.assertEqual(r1["payable"], False)
            self.assertNotIn("balance", r1)
            # walletB had a 1.0 difficulty share, a rejected 10.0 share (ignored), and a 0.05 low-difficulty share (ignored)
            self.assertEqual(r1["shares"].get("walletB"), 1.0)
            self.assertNotIn("walletA", r1["shares"])

            # Immature round checks
            r2 = rounds[2]
            self.assertEqual(r2["candidate_hash"], "hash-immature")
            self.assertEqual(r2["status"], "immature")
            self.assertEqual(r2["payable"], False)
            self.assertNotIn("balance", r2)
            self.assertEqual(r2["shares"].get("walletA"), 2.0)

            # Confirmed round checks
            r3 = rounds[3]
            self.assertEqual(r3["candidate_hash"], "hash-confirmed")
            self.assertEqual(r3["status"], "confirmed")
            # For confirmed rounds, MUST NOT expose balance, payable, earned, paid, or reward-ready fields
            self.assertNotIn("payable", r3)
            self.assertNotIn("balance", r3)
            self.assertNotIn("earned", r3)
            self.assertNotIn("paid", r3)
            self.assertNotIn("reward-ready", r3)
            self.assertEqual(r3["shares"].get("walletC"), 3.0)
