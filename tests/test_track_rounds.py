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
            self.assertEqual(r0["shares"]["walletA"]["share_count"], 1)
            self.assertEqual(r0["shares"]["walletA"]["share_score"], 0.5)
            self.assertEqual(r0["shares"]["walletA"]["workers"]["default"]["share_count"], 1)
            self.assertEqual(r0["shares"]["walletA"]["workers"]["default"]["share_score"], 0.5)
            self.assertEqual(r0["total_share_count"], 1)
            self.assertEqual(r0["total_share_score"], 0.5)
            self.assertEqual(r0["wallet_count"], 1)
            self.assertEqual(r0["worker_count"], 1)

            # chain_match_found round checks
            r1 = rounds[1]
            self.assertEqual(r1["candidate_hash"], "hash-chain-match")
            self.assertEqual(r1["status"], "chain_match_found")
            self.assertEqual(r1["payable"], False)
            self.assertNotIn("balance", r1)
            # walletB had a 1.0 difficulty share, a rejected 10.0 share (ignored), and a 0.05 low-difficulty share (ignored)
            self.assertEqual(r1["shares"]["walletB"]["share_count"], 1)
            self.assertEqual(r1["shares"]["walletB"]["share_score"], 1.0)
            self.assertEqual(r1["total_share_count"], 1)
            self.assertEqual(r1["total_share_score"], 1.0)
            self.assertEqual(r1["wallet_count"], 1)
            self.assertEqual(r1["worker_count"], 1)
            self.assertNotIn("walletA", r1["shares"])

            # Immature round checks
            r2 = rounds[2]
            self.assertEqual(r2["candidate_hash"], "hash-immature")
            self.assertEqual(r2["status"], "immature")
            self.assertEqual(r2["payable"], False)
            self.assertNotIn("balance", r2)
            self.assertEqual(r2["shares"]["walletA"]["share_count"], 1)
            self.assertEqual(r2["shares"]["walletA"]["share_score"], 2.0)
            self.assertEqual(r2["total_share_count"], 1)
            self.assertEqual(r2["total_share_score"], 2.0)

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
            self.assertEqual(r3["shares"]["walletC"]["share_count"], 1)
            self.assertEqual(r3["shares"]["walletC"]["share_score"], 3.0)
            self.assertEqual(r3["total_share_count"], 1)
            self.assertEqual(r3["total_share_score"], 3.0)

    def test_boundary_conditions_and_idempotency(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cand_path = Path(tmpdir) / "accepted-candidates.json"
            share_log = Path(tmpdir) / "share-events.jsonl"
            act_path = Path(tmpdir) / "activity-snapshot.json"
            out_path1 = Path(tmpdir) / "rounds-snapshot-1.json"
            out_path2 = Path(tmpdir) / "rounds-snapshot-2.json"

            # 1. Setup candidates, including duplicate submit_timestamps
            # Duplicate submit timestamp at 12:05:00Z for hash-dup1 and hash-dup2
            candidates_data = {
                "accepted_candidates": [
                    {
                        "candidate_hash": "hash-r1",
                        "lifecycle_status": "confirmed",
                        "matched_height": 200,
                        "submit_timestamp": "2026-06-05T12:00:00Z",
                        "confirmations": 150,
                    },
                    {
                        "candidate_hash": "hash-dup1",
                        "lifecycle_status": "confirmed",
                        "matched_height": 201,
                        "submit_timestamp": "2026-06-05T12:05:00Z",
                        "confirmations": 149,
                    },
                    {
                        "candidate_hash": "hash-dup2",
                        "lifecycle_status": "orphan",
                        "matched_height": None,
                        "submit_timestamp": "2026-06-05T12:05:00Z",
                        "confirmations": None,
                    },
                ]
            }
            with cand_path.open("w", encoding="utf-8") as f:
                json.dump(candidates_data, f)

            # 2. Setup shares:
            # - one share exactly at 12:00:00Z (end of round 1). Should belong to hash-r1.
            # - one share using login format "walletA.worker1" at 12:02:00Z. Should resolve to walletA.
            # - one share using login format "walletA.worker2" at 12:03:00Z. Should resolve to walletA.
            # - one share exactly at 12:05:00Z (end of round 2). Should belong to hash-dup1.
            shares = [
                {
                    "wallet": "walletA",
                    "timestamp": "2026-06-05T12:00:00Z",
                    "accepted": True,
                    "submit": {"difficulty": 1.0},
                },
                {
                    "login": "walletA.worker1",
                    "timestamp": "2026-06-05T12:02:00Z",
                    "accepted": True,
                    "submit": {"difficulty": 0.5},
                },
                {
                    "login": "walletA.worker2",
                    "timestamp": "2026-06-05T12:03:00Z",
                    "accepted": True,
                    "submit": {"difficulty": 0.5},
                },
                {
                    "wallet": "walletB",
                    "timestamp": "2026-06-05T12:05:00Z",
                    "accepted": True,
                    "submit": {"difficulty": 2.0},
                },
            ]
            with share_log.open("w", encoding="utf-8") as f:
                for s in shares:
                    f.write(json.dumps(s) + "\n")

            # Activity snapshot with assumed diff floor
            act_data = {"meta": {"assumedShareDifficulty": 0.1}}
            with act_path.open("w", encoding="utf-8") as f:
                json.dump(act_data, f)

            # 3. First execution
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
                str(out_path1),
            ]
            try:
                exit_code1 = track_rounds.main()
                self.assertEqual(exit_code1, 0)
            finally:
                sys.argv = orig_argv

            # Load and verify first run
            data1 = json.loads(out_path1.read_text(encoding="utf-8"))
            rounds1 = data1["rounds"]
            self.assertEqual(len(rounds1), 3)

            # Check boundary conditions
            # hash-r1 (<= 12:00:00Z) should have walletA: 1.0
            r1 = rounds1[0]
            self.assertEqual(r1["candidate_hash"], "hash-r1")
            self.assertEqual(r1["shares"]["walletA"]["share_count"], 1)
            self.assertEqual(r1["shares"]["walletA"]["share_score"], 1.0)
            self.assertEqual(r1["total_share_count"], 1)
            self.assertEqual(r1["total_share_score"], 1.0)
            self.assertEqual(r1["wallet_count"], 1)
            self.assertEqual(r1["worker_count"], 1)

            # hash-dup1 (12:00:00Z < ts <= 12:05:00Z) should have walletA: 1.0 (0.5 from worker1 + 0.5 from worker2) and walletB: 2.0
            dup1 = rounds1[1]
            self.assertEqual(dup1["candidate_hash"], "hash-dup1")
            self.assertEqual(dup1["shares"]["walletA"]["share_count"], 2)
            self.assertEqual(dup1["shares"]["walletA"]["share_score"], 1.0)
            self.assertEqual(dup1["shares"]["walletA"]["workers"]["worker1"]["share_count"], 1)
            self.assertEqual(dup1["shares"]["walletA"]["workers"]["worker1"]["share_score"], 0.5)
            self.assertEqual(dup1["shares"]["walletA"]["workers"]["worker2"]["share_count"], 1)
            self.assertEqual(dup1["shares"]["walletA"]["workers"]["worker2"]["share_score"], 0.5)
            self.assertEqual(dup1["shares"]["walletB"]["share_count"], 1)
            self.assertEqual(dup1["shares"]["walletB"]["share_score"], 2.0)
            self.assertEqual(dup1["total_share_count"], 3)
            self.assertEqual(dup1["total_share_score"], 3.0)
            self.assertEqual(dup1["wallet_count"], 2)
            self.assertEqual(dup1["worker_count"], 3)

            # hash-dup2 (12:05:00Z < ts <= 12:05:00Z) is empty range, should have 0 shares
            dup2 = rounds1[2]
            self.assertEqual(dup2["candidate_hash"], "hash-dup2")
            self.assertEqual(dup2["total_share_count"], 0)
            self.assertEqual(dup2["total_share_score"], 0.0)
            self.assertEqual(dup2["wallet_count"], 0)
            self.assertEqual(dup2["worker_count"], 0)

            # 4. Second execution (testing repeated run idempotence)
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
                str(out_path2),
            ]
            try:
                exit_code2 = track_rounds.main()
                self.assertEqual(exit_code2, 0)
            finally:
                sys.argv = orig_argv

            data2 = json.loads(out_path2.read_text(encoding="utf-8"))
            
            # Since updated_at is timestamped at the time of writing, they might differ by a tiny fraction.
            # Strip updated_at to compare the core logic output
            data1_stripped = {k: v for k, v in data1.items() if k != "updated_at"}
            data2_stripped = {k: v for k, v in data2.items() if k != "updated_at"}
            self.assertEqual(data1_stripped, data2_stripped)

