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
            self.assertEqual(r0["shares"]["walletA"]["share_percent"], 100.0)
            self.assertEqual(r0["shares"]["walletA"]["workers"]["default"]["share_count"], 1)
            self.assertEqual(r0["shares"]["walletA"]["workers"]["default"]["share_score"], 0.5)
            self.assertEqual(r0["shares"]["walletA"]["workers"]["default"]["share_percent"], 100.0)
            self.assertEqual(r0["shares"]["walletA"]["workers"]["default"]["wallet_share_percent"], 100.0)
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
            # Orphans do not split non-orphan attribution windows, so walletA's pre-orphan share remains observable here.
            self.assertEqual(r1["shares"]["walletA"]["share_count"], 1)
            self.assertEqual(r1["shares"]["walletB"]["share_count"], 1)
            self.assertEqual(r1["shares"]["walletB"]["share_score"], 1.0)
            self.assertEqual(r1["total_share_count"], 2)
            self.assertEqual(r1["total_share_score"], 1.5)
            self.assertEqual(r1["wallet_count"], 2)
            self.assertEqual(r1["worker_count"], 2)

            # Immature round checks
            r2 = rounds[2]
            self.assertEqual(r2["candidate_hash"], "hash-immature")
            self.assertEqual(r2["status"], "immature")
            self.assertEqual(r2["payable"], False)
            self.assertNotIn("balance", r2)
            self.assertEqual(r2["shares"]["walletA"]["share_count"], 1)
            self.assertEqual(r2["shares"]["walletA"]["share_score"], 2.0)
            self.assertEqual(r2["shares"]["walletA"]["share_percent"], 100.0)
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
            self.assertEqual(r3["shares"]["walletC"]["share_percent"], 100.0)
            self.assertEqual(r3["total_share_count"], 1)
            self.assertEqual(r3["total_share_score"], 3.0)
            self.assertEqual(r3["attribution_status"], "ok")
            self.assertIsNone(r3["attribution_reason"])
            self.assertEqual(data["shareLogLinesRead"], len(shares))
            self.assertEqual(data["parsedAcceptedShares"], 4)
            self.assertEqual(data["earliestShareTimestamp"], "2026-06-05T11:59:00Z")
            self.assertEqual(data["latestShareTimestamp"], "2026-06-05T12:12:00Z")
            self.assertEqual(data["emptyConfirmedRoundCount"], 0)

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
            self.assertEqual(r1["shares"]["walletA"]["share_percent"], 100.0)
            self.assertEqual(r1["total_share_count"], 1)
            self.assertEqual(r1["total_share_score"], 1.0)
            self.assertEqual(r1["wallet_count"], 1)
            self.assertEqual(r1["worker_count"], 1)

            # hash-dup1 (12:00:00Z < ts <= 12:05:00Z) should have walletA: 1.0 (0.5 from worker1 + 0.5 from worker2) and walletB: 2.0
            dup1 = rounds1[1]
            self.assertEqual(dup1["candidate_hash"], "hash-dup1")
            self.assertEqual(dup1["shares"]["walletA"]["share_count"], 2)
            self.assertEqual(dup1["shares"]["walletA"]["share_score"], 1.0)
            # walletA = 1.0 / 3.0 * 100 ≈ 33.333333%
            self.assertAlmostEqual(dup1["shares"]["walletA"]["share_percent"], 100 / 3, places=4)
            self.assertEqual(dup1["shares"]["walletA"]["workers"]["worker1"]["share_count"], 1)
            self.assertEqual(dup1["shares"]["walletA"]["workers"]["worker1"]["share_score"], 0.5)
            # worker1 = 0.5 / 3.0 * 100 ≈ 16.666667%
            self.assertAlmostEqual(dup1["shares"]["walletA"]["workers"]["worker1"]["share_percent"], 50 / 3, places=4)
            # worker1 wallet_share_percent = 0.5 / 1.0 * 100 = 50%
            self.assertAlmostEqual(dup1["shares"]["walletA"]["workers"]["worker1"]["wallet_share_percent"], 50.0, places=4)
            self.assertEqual(dup1["shares"]["walletA"]["workers"]["worker2"]["share_count"], 1)
            self.assertEqual(dup1["shares"]["walletA"]["workers"]["worker2"]["share_score"], 0.5)
            self.assertEqual(dup1["shares"]["walletB"]["share_count"], 1)
            self.assertEqual(dup1["shares"]["walletB"]["share_score"], 2.0)
            # walletB = 2.0 / 3.0 * 100 ≈ 66.666667%
            self.assertAlmostEqual(dup1["shares"]["walletB"]["share_percent"], 200 / 3, places=4)
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


class TestRoundSharePercent(unittest.TestCase):
    """Focused tests for share percent correctness."""

    def _run_track(
        self,
        candidates_data,
        shares,
        act_data=None,
        min_diff=None,
        max_share_lines=None,
        existing_output=None,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            cand_path = Path(tmpdir) / "accepted-candidates.json"
            share_log = Path(tmpdir) / "share-events.jsonl"
            act_path = Path(tmpdir) / "activity-snapshot.json"
            out_path = Path(tmpdir) / "rounds-snapshot.json"

            with cand_path.open("w", encoding="utf-8") as f:
                json.dump(candidates_data, f)
            with share_log.open("w", encoding="utf-8") as f:
                for s in shares:
                    f.write(json.dumps(s) + "\n")
            act_payload = act_data or {"meta": {"assumedShareDifficulty": 0.001}}
            with act_path.open("w", encoding="utf-8") as f:
                json.dump(act_payload, f)
            if existing_output is not None:
                with out_path.open("w", encoding="utf-8") as f:
                    json.dump(existing_output, f)

            argv = [
                "track_rounds.py",
                "--accepted-candidates", str(cand_path),
                "--share-log", str(share_log),
                "--activity-snapshot", str(act_path),
                "--output", str(out_path),
            ]
            if min_diff is not None:
                argv += ["--min-share-difficulty", str(min_diff)]
            if max_share_lines is not None:
                argv += ["--max-share-lines", str(max_share_lines)]

            orig_argv = sys.argv
            sys.argv = argv
            try:
                exit_code = track_rounds.main()
            finally:
                sys.argv = orig_argv

            self.assertEqual(exit_code, 0)
            return json.loads(out_path.read_text(encoding="utf-8"))

    def test_single_wallet_is_100_percent(self):
        """A round with one wallet should report 100% share_percent."""
        data = self._run_track(
            candidates_data={
                "accepted_candidates": [{
                    "candidate_hash": "hash-solo",
                    "lifecycle_status": "confirmed",
                    "matched_height": 500,
                    "submit_timestamp": "2026-06-05T13:00:00Z",
                    "confirmations": 120,
                }]
            },
            shares=[
                {
                    "wallet": "walletSolo",
                    "timestamp": "2026-06-05T12:55:00Z",
                    "accepted": True,
                    "submit": {"difficulty": 5.0},
                },
                {
                    "wallet": "walletSolo",
                    "timestamp": "2026-06-05T12:57:00Z",
                    "accepted": True,
                    "submit": {"difficulty": 3.0},
                },
            ],
        )
        rounds = data["rounds"]
        self.assertEqual(len(rounds), 1)
        r = rounds[0]
        self.assertEqual(r["total_share_score"], 8.0)
        self.assertEqual(r["shares"]["walletSolo"]["share_percent"], 100.0)
        for wk_data in r["shares"]["walletSolo"]["workers"].values():
            self.assertEqual(wk_data["wallet_share_percent"], 100.0)

    def test_multi_wallet_split_percent(self):
        """Two wallets with known scores should split percentages correctly."""
        data = self._run_track(
            candidates_data={
                "accepted_candidates": [{
                    "candidate_hash": "hash-split",
                    "lifecycle_status": "immature",
                    "matched_height": 600,
                    "submit_timestamp": "2026-06-05T14:00:00Z",
                    "confirmations": 10,
                }]
            },
            shares=[
                # walletA contributes 1.0 (25%)
                {
                    "wallet": "walletA",
                    "timestamp": "2026-06-05T13:55:00Z",
                    "accepted": True,
                    "submit": {"difficulty": 1.0},
                },
                # walletB contributes 3.0 (75%)
                {
                    "wallet": "walletB",
                    "timestamp": "2026-06-05T13:56:00Z",
                    "accepted": True,
                    "submit": {"difficulty": 3.0},
                },
            ],
        )
        rounds = data["rounds"]
        r = rounds[0]
        self.assertEqual(r["total_share_score"], 4.0)
        self.assertAlmostEqual(r["shares"]["walletA"]["share_percent"], 25.0, places=4)
        self.assertAlmostEqual(r["shares"]["walletB"]["share_percent"], 75.0, places=4)

    def test_multi_worker_under_one_wallet(self):
        """Multiple workers under one wallet should split wallet_share_percent correctly."""
        data = self._run_track(
            candidates_data={
                "accepted_candidates": [{
                    "candidate_hash": "hash-workers",
                    "lifecycle_status": "confirmed",
                    "matched_height": 700,
                    "submit_timestamp": "2026-06-05T15:00:00Z",
                    "confirmations": 200,
                }]
            },
            shares=[
                {
                    "login": "walletX.rig1",
                    "timestamp": "2026-06-05T14:55:00Z",
                    "accepted": True,
                    "submit": {"difficulty": 6.0},
                },
                {
                    "login": "walletX.rig2",
                    "timestamp": "2026-06-05T14:56:00Z",
                    "accepted": True,
                    "submit": {"difficulty": 2.0},
                },
            ],
        )
        rounds = data["rounds"]
        r = rounds[0]
        self.assertEqual(r["total_share_score"], 8.0)
        # walletX is the sole wallet → 100%
        self.assertEqual(r["shares"]["walletX"]["share_percent"], 100.0)
        # rig1: 6/8 = 75% of round, 6/8 = 75% of wallet
        self.assertAlmostEqual(r["shares"]["walletX"]["workers"]["rig1"]["share_percent"], 75.0, places=4)
        self.assertAlmostEqual(r["shares"]["walletX"]["workers"]["rig1"]["wallet_share_percent"], 75.0, places=4)
        # rig2: 2/8 = 25% of round, 2/8 = 25% of wallet
        self.assertAlmostEqual(r["shares"]["walletX"]["workers"]["rig2"]["share_percent"], 25.0, places=4)
        self.assertAlmostEqual(r["shares"]["walletX"]["workers"]["rig2"]["wallet_share_percent"], 25.0, places=4)

    def test_zero_score_round_does_not_crash(self):
        """A round with no matching shares should produce 0 percent fields (no division by zero)."""
        data = self._run_track(
            candidates_data={
                "accepted_candidates": [{
                    "candidate_hash": "hash-empty",
                    "lifecycle_status": "orphan",
                    "matched_height": 800,
                    "submit_timestamp": "2026-06-05T16:00:00Z",
                    "confirmations": 0,
                }]
            },
            shares=[],  # No shares at all
        )
        rounds = data["rounds"]
        self.assertEqual(len(rounds), 1)
        r = rounds[0]
        self.assertEqual(r["total_share_score"], 0.0)
        self.assertEqual(r["shares"], {})

    def test_rejected_shares_excluded_from_percent(self):
        """Rejected shares must not inflate percent calculations."""
        data = self._run_track(
            candidates_data={
                "accepted_candidates": [{
                    "candidate_hash": "hash-reject",
                    "lifecycle_status": "confirmed",
                    "matched_height": 900,
                    "submit_timestamp": "2026-06-05T17:00:00Z",
                    "confirmations": 150,
                }]
            },
            shares=[
                # Valid share
                {
                    "wallet": "walletGood",
                    "timestamp": "2026-06-05T16:55:00Z",
                    "accepted": True,
                    "submit": {"difficulty": 4.0},
                },
                # Rejected share — must be excluded
                {
                    "wallet": "walletBad",
                    "timestamp": "2026-06-05T16:56:00Z",
                    "accepted": False,
                    "submit": {"difficulty": 100.0},
                },
            ],
        )
        rounds = data["rounds"]
        r = rounds[0]
        # Only walletGood should appear; rejected share must not affect total
        self.assertEqual(r["total_share_score"], 4.0)
        self.assertIn("walletGood", r["shares"])
        self.assertNotIn("walletBad", r["shares"])
        self.assertEqual(r["shares"]["walletGood"]["share_percent"], 100.0)

    def test_confirmed_round_receives_shares_in_window(self):
        data = self._run_track(
            candidates_data={
                "accepted_candidates": [
                    {
                        "candidate_hash": "hash-prev",
                        "lifecycle_status": "confirmed",
                        "matched_height": 999,
                        "submit_timestamp": "2026-06-05T17:55:00Z",
                        "confirmations": 151,
                    },
                    {
                        "candidate_hash": "hash-window",
                        "lifecycle_status": "confirmed",
                        "matched_height": 1000,
                        "submit_timestamp": "2026-06-05T18:00:00Z",
                        "confirmations": 150,
                    },
                ]
            },
            shares=[
                {
                    "wallet": "walletWindow",
                    "timestamp": "2026-06-05T17:56:00Z",
                    "accepted": True,
                    "submit": {"difficulty": 2.5},
                }
            ],
        )
        round_item = data["rounds"][1]
        self.assertEqual(round_item["candidate_hash"], "hash-window")
        self.assertEqual(round_item["total_share_count"], 1)
        self.assertEqual(round_item["shares"]["walletWindow"]["share_score"], 2.5)
        self.assertEqual(round_item["attribution_status"], "ok")
        self.assertIsNone(round_item["attribution_reason"])

    def test_confirmed_round_receives_shares_from_rotated_segment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cand_path = root / "accepted-candidates.json"
            share_log = root / "share-events.jsonl"
            act_path = root / "activity-snapshot.json"
            out_path = root / "rounds-snapshot.json"
            rotated_log = root / (
                "share-events."
                "00000000000000000001-00000000000000000002.jsonl"
            )

            with cand_path.open("w", encoding="utf-8") as f:
                json.dump({
                    "accepted_candidates": [
                        {
                            "candidate_hash": "hash-prev",
                            "lifecycle_status": "confirmed",
                            "matched_height": 999,
                            "submit_timestamp": "2026-06-05T17:55:00Z",
                            "confirmations": 151,
                        },
                        {
                            "candidate_hash": "hash-window",
                            "lifecycle_status": "confirmed",
                            "matched_height": 1000,
                            "submit_timestamp": "2026-06-05T18:00:00Z",
                            "confirmations": 150,
                        },
                    ]
                }, f)
            with rotated_log.open("w", encoding="utf-8") as f:
                f.write(json.dumps({
                    "wallet": "walletWindow",
                    "timestamp": "2026-06-05T17:56:00Z",
                    "accepted": True,
                    "submit": {"difficulty": 2.5},
                }) + "\n")
            with share_log.open("w", encoding="utf-8") as f:
                f.write(json.dumps({
                    "wallet": "walletLater",
                    "timestamp": "2026-06-05T18:05:00Z",
                    "accepted": True,
                    "submit": {"difficulty": 1.0},
                }) + "\n")
            with act_path.open("w", encoding="utf-8") as f:
                json.dump({"meta": {"assumedShareDifficulty": 0.001}}, f)

            orig_argv = sys.argv
            sys.argv = [
                "track_rounds.py",
                "--accepted-candidates", str(cand_path),
                "--share-log", str(share_log),
                "--activity-snapshot", str(act_path),
                "--output", str(out_path),
            ]
            try:
                exit_code = track_rounds.main()
                self.assertEqual(exit_code, 0)
            finally:
                sys.argv = orig_argv

            data = json.loads(out_path.read_text(encoding="utf-8"))
            round_item = data["rounds"][1]
            self.assertEqual(data["shareLogLinesRead"], 2)
            self.assertEqual(data["shareLogSegmentCount"], 2)
            self.assertEqual(round_item["candidate_hash"], "hash-window")
            self.assertEqual(round_item["total_share_count"], 1)
            self.assertEqual(round_item["shares"]["walletWindow"]["share_score"], 2.5)
            self.assertEqual(round_item["attribution_status"], "ok")
            self.assertIsNone(round_item["attribution_reason"])

    def test_empty_confirmed_round_old_timestamp_marks_tail_too_short(self):
        data = self._run_track(
            candidates_data={
                "accepted_candidates": [{
                    "candidate_hash": "hash-tail-short",
                    "lifecycle_status": "confirmed",
                    "matched_height": 1100,
                    "submit_timestamp": "2026-06-05T18:00:00Z",
                    "confirmations": 150,
                }]
            },
            shares=[
                {
                    "wallet": "walletLater",
                    "timestamp": "2026-06-05T18:05:00Z",
                    "accepted": True,
                    "submit": {"difficulty": 1.0},
                }
            ],
        )
        round_item = data["rounds"][0]
        self.assertEqual(round_item["total_share_count"], 0)
        self.assertEqual(round_item["attribution_status"], "incomplete")
        self.assertEqual(round_item["attribution_reason"], "share_log_tail_too_short")

    def test_empty_confirmed_round_with_covered_window_marks_no_shares(self):
        data = self._run_track(
            candidates_data={
                "accepted_candidates": [{
                    "candidate_hash": "hash-empty-covered",
                    "lifecycle_status": "confirmed",
                    "matched_height": 1200,
                    "submit_timestamp": "2026-06-05T18:00:00Z",
                    "confirmations": 150,
                }]
            },
            shares=[
                {
                    "wallet": "walletEarlier",
                    "timestamp": "2026-06-05T17:55:00Z",
                    "accepted": True,
                    "submit": {"difficulty": 1.0},
                }
            ],
        )
        round_item = data["rounds"][0]
        self.assertEqual(round_item["total_share_count"], 1)
        self.assertEqual(round_item["attribution_status"], "ok")

        data = self._run_track(
            candidates_data={
                "accepted_candidates": [
                    {
                        "candidate_hash": "hash-boundary",
                        "lifecycle_status": "confirmed",
                        "matched_height": 1200,
                        "submit_timestamp": "2026-06-05T17:56:00Z",
                        "confirmations": 151,
                    },
                    {
                        "candidate_hash": "hash-empty-covered",
                        "lifecycle_status": "confirmed",
                        "matched_height": 1201,
                        "submit_timestamp": "2026-06-05T18:00:00Z",
                        "confirmations": 150,
                    },
                ]
            },
            shares=[
                {
                    "wallet": "walletBoundary",
                    "timestamp": "2026-06-05T17:55:00Z",
                    "accepted": True,
                    "submit": {"difficulty": 1.0},
                }
            ],
        )
        round_item = data["rounds"][1]
        self.assertEqual(round_item["total_share_count"], 0)
        self.assertEqual(round_item["attribution_status"], "empty")
        self.assertEqual(round_item["attribution_reason"], "no_shares_in_round_window")

    def test_metadata_includes_share_tail_and_empty_counts(self):
        data = self._run_track(
            candidates_data={
                "accepted_candidates": [{
                    "candidate_hash": "hash-meta-empty",
                    "lifecycle_status": "confirmed",
                    "matched_height": 1300,
                    "submit_timestamp": "2026-06-05T18:00:00Z",
                    "confirmations": 150,
                }]
            },
            shares=[
                {
                    "wallet": "walletMeta",
                    "timestamp": "2026-06-05T18:01:00Z",
                    "accepted": True,
                    "submit": {"difficulty": 1.0},
                },
                {
                    "wallet": "walletMeta",
                    "timestamp": "2026-06-05T18:02:00Z",
                    "accepted": False,
                    "submit": {"difficulty": 1.0},
                },
            ],
            max_share_lines=100000,
        )
        self.assertEqual(data["shareLogLinesRead"], 2)
        self.assertEqual(data["parsedAcceptedShares"], 1)
        self.assertEqual(data["earliestShareTimestamp"], "2026-06-05T18:01:00Z")
        self.assertEqual(data["latestShareTimestamp"], "2026-06-05T18:01:00Z")
        self.assertEqual(data["incompleteConfirmedRoundCount"], 1)
        self.assertEqual(data["emptyConfirmedRoundCount"], 0)
        self.assertEqual(data["preservedRoundAttributionCount"], 0)
        self.assertEqual(data["maxShareLines"], 100000)

    def test_orphan_does_not_split_next_confirmed_payout_round(self):
        data = self._run_track(
            candidates_data={
                "accepted_candidates": [
                    {
                        "candidate_hash": "hash-orphan-boundary",
                        "lifecycle_status": "orphan",
                        "matched_height": None,
                        "submit_timestamp": "2026-06-05T18:00:00Z",
                        "confirmations": None,
                    },
                    {
                        "candidate_hash": "hash-confirmed-after-orphan",
                        "lifecycle_status": "confirmed",
                        "matched_height": 1400,
                        "submit_timestamp": "2026-06-05T18:05:00Z",
                        "confirmations": 150,
                    },
                ]
            },
            shares=[
                {
                    "wallet": "walletBeforeOrphan",
                    "timestamp": "2026-06-05T17:59:00Z",
                    "accepted": True,
                    "submit": {"difficulty": 1.0},
                },
                {
                    "wallet": "walletAfterOrphan",
                    "timestamp": "2026-06-05T18:02:00Z",
                    "accepted": True,
                    "submit": {"difficulty": 2.0},
                },
            ],
        )
        orphan_round = data["rounds"][0]
        confirmed_round = data["rounds"][1]
        self.assertIn("walletBeforeOrphan", orphan_round["shares"])
        self.assertIn("walletBeforeOrphan", confirmed_round["shares"])
        self.assertIn("walletAfterOrphan", confirmed_round["shares"])
        self.assertEqual(confirmed_round["total_share_count"], 2)

    def test_preserves_existing_non_empty_attribution_when_tail_too_short(self):
        existing_output = {
            "rounds": [{
                "candidate_hash": "hash-preserve",
                "shares": {
                    "walletOld": {
                        "share_count": 2,
                        "share_score": 4.0,
                        "share_percent": 100.0,
                        "workers": {
                            "rig1": {
                                "share_count": 2,
                                "share_score": 4.0,
                                "share_percent": 100.0,
                                "wallet_share_percent": 100.0,
                            }
                        },
                    }
                },
                "total_share_count": 2,
                "total_share_score": 4.0,
                "wallet_count": 1,
                "worker_count": 1,
            }]
        }
        data = self._run_track(
            candidates_data={
                "accepted_candidates": [{
                    "candidate_hash": "hash-preserve",
                    "lifecycle_status": "confirmed",
                    "matched_height": 1500,
                    "submit_timestamp": "2026-06-05T18:00:00Z",
                    "confirmations": 150,
                }]
            },
            shares=[{
                "wallet": "walletLater",
                "timestamp": "2026-06-05T18:05:00Z",
                "accepted": True,
                "submit": {"difficulty": 1.0},
            }],
            existing_output=existing_output,
        )
        round_item = data["rounds"][0]
        self.assertEqual(round_item["attribution_status"], "preserved")
        self.assertEqual(round_item["attribution_reason"], "preserved_existing_attribution_after_tail_short")
        self.assertTrue(round_item["attribution_preserved"])
        self.assertIn("attribution_preserved_at", round_item)
        self.assertEqual(round_item["shares"], existing_output["rounds"][0]["shares"])
        self.assertEqual(round_item["total_share_count"], 2)
        self.assertEqual(round_item["total_share_score"], 4.0)
        self.assertEqual(round_item["wallet_count"], 1)
        self.assertEqual(round_item["worker_count"], 1)
        self.assertEqual(data["preservedRoundAttributionCount"], 1)
        self.assertEqual(data["incompleteConfirmedRoundCount"], 0)

    def test_existing_empty_attribution_is_not_preserved(self):
        existing_output = {
            "rounds": [{
                "candidate_hash": "hash-empty-existing",
                "shares": {},
                "total_share_count": 0,
                "total_share_score": 0.0,
                "wallet_count": 0,
                "worker_count": 0,
            }]
        }
        data = self._run_track(
            candidates_data={
                "accepted_candidates": [{
                    "candidate_hash": "hash-empty-existing",
                    "lifecycle_status": "confirmed",
                    "matched_height": 1501,
                    "submit_timestamp": "2026-06-05T18:00:00Z",
                    "confirmations": 150,
                }]
            },
            shares=[{
                "wallet": "walletLater",
                "timestamp": "2026-06-05T18:05:00Z",
                "accepted": True,
                "submit": {"difficulty": 1.0},
            }],
            existing_output=existing_output,
        )
        round_item = data["rounds"][0]
        self.assertEqual(round_item["total_share_count"], 0)
        self.assertEqual(round_item["attribution_status"], "incomplete")
        self.assertEqual(round_item["attribution_reason"], "share_log_tail_too_short")
        self.assertNotIn("attribution_preserved", round_item)
        self.assertEqual(data["preservedRoundAttributionCount"], 0)
        self.assertEqual(data["incompleteConfirmedRoundCount"], 1)

    def test_new_non_empty_attribution_replaces_existing_preserved_data(self):
        existing_output = {
            "rounds": [{
                "candidate_hash": "hash-replace",
                "shares": {
                    "walletOld": {
                        "share_count": 1,
                        "share_score": 1.0,
                        "share_percent": 100.0,
                        "workers": {
                            "default": {
                                "share_count": 1,
                                "share_score": 1.0,
                                "share_percent": 100.0,
                                "wallet_share_percent": 100.0,
                            }
                        },
                    }
                },
                "total_share_count": 1,
                "total_share_score": 1.0,
                "wallet_count": 1,
                "worker_count": 1,
                "attribution_status": "preserved",
            }]
        }
        data = self._run_track(
            candidates_data={
                "accepted_candidates": [{
                    "candidate_hash": "hash-replace",
                    "lifecycle_status": "confirmed",
                    "matched_height": 1502,
                    "submit_timestamp": "2026-06-05T18:00:00Z",
                    "confirmations": 150,
                }]
            },
            shares=[{
                "wallet": "walletNew",
                "timestamp": "2026-06-05T17:59:00Z",
                "accepted": True,
                "submit": {"difficulty": 3.0},
            }],
            existing_output=existing_output,
        )
        round_item = data["rounds"][0]
        self.assertEqual(round_item["attribution_status"], "ok")
        self.assertIsNone(round_item["attribution_reason"])
        self.assertNotIn("walletOld", round_item["shares"])
        self.assertEqual(round_item["shares"]["walletNew"]["share_count"], 1)
        self.assertEqual(round_item["total_share_count"], 1)
        self.assertEqual(round_item["total_share_score"], 3.0)
        self.assertEqual(data["preservedRoundAttributionCount"], 0)
